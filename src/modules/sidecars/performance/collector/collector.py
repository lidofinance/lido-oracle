import logging
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import TimeoutError as DecoratorTimeoutError

from src import variables
from src.metrics.prometheus.performance_collector import (
    PERFORMANCE_COLLECTOR_DB_DEMAND_COUNT,
    PERFORMANCE_COLLECTOR_ERRORS_TOTAL,
)
from src.modules.common.daemon_module import DaemonModule
from src.modules.common.types import ChainConfig, ModuleExecuteDelay
from src.modules.sidecars.performance.collector.checkpoint import (
    FrameCheckpointProcessor,
    FrameCheckpointsIterator,
)
from src.modules.sidecars.performance.common.db import DutiesDB
from src.providers.consensus.client import ConsensusClient
from src.providers.http_provider import NotOkResponse
from src.types import BlockStamp, EpochNumber
from src.utils.slot import InconsistentData, NoSlotsAvailable, SlotNotFinalized
from src.utils.web3converter import ChainConverter


logger = logging.getLogger(__name__)


class PerformanceCollector(DaemonModule):
    """
    Continuously collects performance data from Consensus Layer into db for the given epoch range.
    """

    # Datetime of the last epochs demand update
    last_epochs_demand_update: datetime | None = None
    last_demands_count: int = 0

    def __init__(self, cc: ConsensusClient):
        super().__init__(cc=cc)
        self.db = DutiesDB(
            connect_timeout=variables.PERFORMANCE_COLLECTOR_DB_CONNECTION_TIMEOUT,
            statement_timeout_ms=variables.PERFORMANCE_COLLECTOR_DB_STATEMENT_TIMEOUT_MS,
        )
        self.last_epochs_demand_update = self.db.get_epochs_demands_max_updated_at()
        self.last_demands_count = self.db.demands_count()

    @contextmanager
    def exception_handler(self) -> Iterator[None]:
        """Context manager for handling Performance Collector exceptions"""
        try:
            yield
        except DecoratorTimeoutError as error:
            logger.error({'msg': 'Performance collector does not respond.', 'error': str(error)})
            PERFORMANCE_COLLECTOR_ERRORS_TOTAL.labels(type="timeout").inc()
        except RequestsConnectionError as error:
            logger.error({'msg': 'Connection error.', 'error': str(error)})
            PERFORMANCE_COLLECTOR_ERRORS_TOTAL.labels(type="connection").inc()
        except NotOkResponse as error:
            logger.error({'msg': ''.join(traceback.format_exception(error))})
            PERFORMANCE_COLLECTOR_ERRORS_TOTAL.labels(type="not_ok_response").inc()
        except (NoSlotsAvailable, SlotNotFinalized, InconsistentData) as error:
            logger.error({'msg': 'Inconsistent response from consensus layer node.', 'error': str(error)})
            PERFORMANCE_COLLECTOR_ERRORS_TOTAL.labels(type="inconsistent_data").inc()
        except ValueError as error:
            logger.error({'msg': 'Unexpected error.', 'error': str(error)})
            PERFORMANCE_COLLECTOR_ERRORS_TOTAL.labels(type="value_error").inc()
        except Exception as error:
            PERFORMANCE_COLLECTOR_ERRORS_TOTAL.labels(type="unknown").inc()
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

        self._update_demand_metrics()

        epochs_range_to_process = self._define_epochs_to_process_range(finalized_epoch)
        if not epochs_range_to_process:
            return ModuleExecuteDelay.NEXT_SLOT
        start_epoch, end_epoch = epochs_range_to_process

        checkpoints = FrameCheckpointsIterator(
            converter,
            start_epoch,
            end_epoch,
            finalized_epoch,
        )
        processor = FrameCheckpointProcessor(
            self.cc,
            self.db,
            converter,
            last_finalized_blockstamp,
        )

        checkpoint_count = 0
        for checkpoint in checkpoints:
            processed_epochs = processor.exec(checkpoint)
            checkpoint_count += 1
            logger.info(
                {
                    'msg': 'Checkpoint processing completed',
                    'checkpoint_slot': checkpoint.slot,
                    'processed_epochs': processed_epochs,
                }
            )
            # Reset base cycle timeout to avoid timeout errors during long checkpoints processing
            self._reset_cycle_timeout()

            if self._has_epochs_demand_changed():
                logger.info({"msg": "Epochs demand change detected during processing"})
                return ModuleExecuteDelay.NEXT_SLOT

        logger.info({'msg': 'All checkpoints processing completed', 'total_checkpoints_processed': checkpoint_count})

        return ModuleExecuteDelay.NEXT_SLOT

    def _update_demand_metrics(self) -> None:
        PERFORMANCE_COLLECTOR_DB_DEMAND_COUNT.set(self.db.demands_count())

    def _define_epochs_to_process_range(self, finalized_epoch: EpochNumber) -> tuple[EpochNumber, EpochNumber] | None:
        max_available_epoch_to_check = finalized_epoch - FrameCheckpointsIterator.CHECKPOINT_SLOT_DELAY_EPOCHS
        if max_available_epoch_to_check < 0:
            logger.info({"msg": "No available epochs to process yet"})
            return None

        min_epoch_in_db = self.db.min_epoch()
        max_epoch_in_db = self.db.max_epoch()

        if min_epoch_in_db and min_epoch_in_db > max_available_epoch_to_check:
            raise ValueError("DB has data for a not‑yet‑finalised epoch. CL node is not synced.")

        start_epoch = EpochNumber(min_epoch_in_db if min_epoch_in_db is not None else max_available_epoch_to_check)
        end_epoch = EpochNumber(max_available_epoch_to_check)

        epochs_demand = self.db.get_epochs_demands()
        if not epochs_demand:
            logger.info({"msg": "No epoch demands found"})
        for demand in epochs_demand:
            logger.info({"msg": "Epochs demand", **demand.model_dump()})
            is_range_available = self.db.is_range_available(
                EpochNumber(demand.from_epoch), EpochNumber(demand.to_epoch)
            )
            if is_range_available:
                logger.info(
                    {
                        "msg": f"Epochs demand for {demand.consumer} is already satisfied",
                    }
                )
                # Remove from the DB just in case
                self.db.delete_demand(demand)
                # There is no sense to lower start_epoch because the demand is already satisfied (data is in the DB)
                continue
            start_epoch = EpochNumber(min(start_epoch, demand.from_epoch))

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

    def _has_epochs_demand_changed(self) -> bool:
        max_updated_at = self.db.get_epochs_demands_max_updated_at()
        count = self.db.demands_count()
        changed = count != self.last_demands_count or (
            max_updated_at is not None and self.last_epochs_demand_update != max_updated_at
        )
        if changed:
            self.last_epochs_demand_update = max_updated_at
            self.last_demands_count = count
            self._update_demand_metrics()
            return True
        return False
