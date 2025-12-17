import logging
import traceback
from contextlib import contextmanager
from typing import Iterator

from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import TimeoutError as DecoratorTimeoutError

from src import variables
from src.modules.common.daemon_module import DaemonModule
from src.modules.common.types import ModuleExecuteDelay, ChainConfig
from src.modules.sidecars.performance.collector.checkpoint import (
    FrameCheckpointsIterator,
    FrameCheckpointProcessor,
)
from src.modules.sidecars.performance.common.db import DutiesDB
from src.providers.consensus.client import ConsensusClient
from src.providers.http_provider import NotOkResponse
from src.types import BlockStamp, EpochNumber, SlotNumber
from src.utils.slot import InconsistentData, NoSlotsAvailable, SlotNotFinalized
from src.utils.web3converter import ChainConverter

logger = logging.getLogger(__name__)


class PerformanceCollector(DaemonModule):
    """
    Continuously collects performance data from Consensus Layer into db for the given epoch range.
    """
    _slot_threshold = SlotNumber(0)

    # Timestamp of the last epochs demand update
    last_epochs_demand_update: int = 0

    def __init__(self, cc: ConsensusClient):
        self.cc = cc.cc if hasattr(cc, "cc") else cc
        self.db = DutiesDB(
            connect_timeout=variables.PERFORMANCE_COLLECTOR_DB_CONNECTION_TIMEOUT,
            statement_timeout_ms=variables.PERFORMANCE_COLLECTOR_DB_STATEMENT_TIMEOUT_MS,
        )
        self.last_epochs_demand_update = self.get_epochs_demand_max_updated_at()

    def _get_consensus_client(self):
        """Returns consensus client"""
        return self.cc

    @contextmanager
    def exception_handler(self) -> Iterator[None]:
        """Context manager for handling Performance Collector exceptions"""
        try:
            yield
        except DecoratorTimeoutError as error:
            logger.error({'msg': 'Performance collector do not respond.', 'error': str(error)})
        except RequestsConnectionError as error:
            logger.error({'msg': 'Connection error.', 'error': str(error)})
        except NotOkResponse as error:
            logger.error({'msg': ''.join(traceback.format_exception(error))})
        except (NoSlotsAvailable, SlotNotFinalized, InconsistentData) as error:
            logger.error({'msg': 'Inconsistent response from consensus layer node.', 'error': str(error)})
        except ValueError as error:
            logger.error({'msg': 'Unexpected error.', 'error': str(error)})
        except Exception as error:
            raise error

    def _build_converter(self) -> ChainConverter:
        cc_spec = self.cc.get_config_spec()
        genesis = self.cc.get_genesis()
        chain_cfg = ChainConfig(
            slots_per_epoch=cc_spec.SLOTS_PER_EPOCH,
            seconds_per_slot=cc_spec.SECONDS_PER_SLOT,
            genesis_time=genesis.genesis_time,
        )
        return ChainConverter(chain_cfg)

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        converter = self._build_converter()

        # NOTE: Finalized slot is the first slot of justifying epoch, so we need to take the previous. But if the first
        # slot of the justifying epoch is empty, blockstamp.slot_number will point to the slot where the last finalized
        # block was created. As a result, finalized_epoch in this case will be less than the actual number of the last
        # finalized epoch. As a result we can have a delay in frame finalization.
        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(last_finalized_blockstamp.slot_number) - 1)

        epochs_range_to_process = self.define_epochs_to_process_range(finalized_epoch)
        if not epochs_range_to_process:
            return ModuleExecuteDelay.NEXT_SLOT
        start_epoch, end_epoch = epochs_range_to_process

        checkpoints = FrameCheckpointsIterator(
            converter,
            start_epoch,
            end_epoch,
            finalized_epoch,
        )
        processor = FrameCheckpointProcessor(self.cc, self.db, converter, last_finalized_blockstamp)

        checkpoint_count = 0
        for checkpoint in checkpoints:
            processed_epochs = processor.exec(checkpoint)
            checkpoint_count += 1
            logger.info({
                'msg': 'Checkpoint processing completed',
                'checkpoint_slot': checkpoint.slot,
                'processed_epochs': processed_epochs
            })
            # Reset base cycle timeout to avoid timeout errors during long checkpoints processing
            self._reset_cycle_timeout()

            if self.new_epochs_range_demand_appeared():
                logger.info({"msg": "New epochs demand is found during processing"})
                return ModuleExecuteDelay.NEXT_SLOT

        logger.info({
            'msg': 'All checkpoints processing completed',
            'total_checkpoints_processed': checkpoint_count
        })

        return ModuleExecuteDelay.NEXT_SLOT

    def define_epochs_to_process_range(self, finalized_epoch: EpochNumber) -> tuple[EpochNumber, EpochNumber] | None:
        max_available_epoch_to_check = finalized_epoch - FrameCheckpointsIterator.CHECKPOINT_SLOT_DELAY_EPOCHS
        if max_available_epoch_to_check < 0:
            logger.info({"msg": "No available epochs to process yet"})
            return None

        min_epoch_in_db = self.db.min_epoch()
        max_epoch_in_db = self.db.max_epoch()

        if min_epoch_in_db and max_available_epoch_to_check < min_epoch_in_db:
            raise ValueError(
                "Max available epoch to check is lower than the minimum epoch in the DB. CL node is not synced"
            )

        start_epoch = EpochNumber(max_available_epoch_to_check)
        end_epoch = EpochNumber(max_available_epoch_to_check)

        epochs_demand = self.db.get_epochs_demands()
        if not epochs_demand:
            logger.info({"msg": "No epoch demands found"})
        for demand in epochs_demand:
            logger.info({
                "msg": "Epochs demand", **demand.model_dump()
            })
            is_range_available = self.db.is_range_available(EpochNumber(demand.l_epoch), EpochNumber(demand.r_epoch))
            if is_range_available:
                logger.info({
                    "msg": f"Epochs demand for {demand.consumer} is already satisfied",
                })
                # Remove from the DB just in case
                self.db.delete_demand(demand.consumer)
                # There is no sense to lower start_epoch because the demand is already satisfied (data is in the DB)
                continue
            start_epoch = min(start_epoch, EpochNumber(demand.l_epoch))

        missing_epochs = self.db.missing_epochs_in(start_epoch, end_epoch)
        if not missing_epochs:
            if max_epoch_in_db is None:
                raise ValueError("No missing epochs found but the DB is empty. Probably a logic error or corrupted DB.")
            start_epoch = EpochNumber(max_epoch_in_db + 1)
        else:
            start_epoch = min(missing_epochs)

        log_meta_info = {
            "start_epoch": start_epoch,
            "end_epoch": end_epoch,
            "finalized_epoch": finalized_epoch,
            "max_available_epoch_to_check": max_available_epoch_to_check,
            "min_epoch_in_db": min_epoch_in_db,
            "max_epoch_in_db": max_epoch_in_db,
            "missing_epochs": len(missing_epochs) if missing_epochs else 0,
        }

        if start_epoch > max_available_epoch_to_check:
            logger.info({"msg": "No available to process epochs range demand yet", **log_meta_info})
            return None

        logger.info({"msg": "Epochs range to process is determined", **log_meta_info})

        return start_epoch, end_epoch

    def new_epochs_range_demand_appeared(self) -> bool:
        max_updated_at = self.get_epochs_demand_max_updated_at()
        updated = self.last_epochs_demand_update != max_updated_at
        if updated:
            self.last_epochs_demand_update = max_updated_at
            return True
        return False

    def get_epochs_demand_max_updated_at(self) -> int:
        max_updated_at = self.db.get_epochs_demands_max_updated_at()
        return int(max_updated_at) if max_updated_at is not None else 0
