import logging
from typing import Optional, Final

from src.modules.performance_collector.checkpoint import (
    FrameCheckpointsIterator,
    FrameCheckpointProcessor,
)
from src.modules.performance_collector.db import DutiesDB
from src.modules.performance_collector.http_server import start_performance_api_server
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.types import ChainConfig
from src.types import BlockStamp, EpochNumber
from src.utils.web3converter import ChainConverter
from src import variables

logger = logging.getLogger(__name__)


class PerformanceCollector(BaseModule):
    """
    Continuously collects performance data from Consensus Layer into db for the given epoch range.
    """
    # Timestamp of the last epochs demand update
    last_epochs_demand_update: int = 0

    def __init__(self, w3, db_path: Optional[str] = None):
        super().__init__(w3)
        logger.info({'msg': 'Initialize Performance Collector module.'})
        db_path = db_path or str((variables.CACHE_PATH / "eth_duties.sqlite").absolute())
        self.db = DutiesDB(db_path)
        try:
            logger.info(
                {'msg': f'Start performance API server on port {variables.PERFORMANCE_COLLECTOR_SERVER_API_PORT}'}
            )
            start_performance_api_server(db_path)
        except Exception as e:
            logger.error({'msg': 'Failed to start performance API server', 'error': repr(e)})
            raise
        self.last_epochs_demand_update = self.get_epochs_demand_max_updated_at()

    def refresh_contracts(self):
        # No need to refresh contracts for this module. There are no contracts used.
        return None

    def _build_converter(self) -> ChainConverter:
        cc_spec = self.w3.cc.get_config_spec()
        genesis = self.w3.cc.get_genesis()
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

        epochs_range_demand = self.define_epochs_to_process_range(finalized_epoch)
        if not epochs_range_demand:
            return ModuleExecuteDelay.NEXT_SLOT
        start_epoch, end_epoch = epochs_range_demand

        checkpoints = FrameCheckpointsIterator(
            converter,
            start_epoch,
            end_epoch,
            finalized_epoch,
        )
        processor = FrameCheckpointProcessor(self.w3.cc, self.db, converter, last_finalized_blockstamp)

        checkpoint_count = 0
        for checkpoint in checkpoints:
            processed_epochs = processor.exec(checkpoint)
            checkpoint_count += 1
            logger.info({
                'msg': 'Checkpoint processing completed',
                'checkpoint_slot': checkpoint.slot,
                'processed_epochs': processed_epochs
            })
            # Reset BaseOracle cycle timeout to avoid timeout errors during long checkpoints processing
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

        epochs_demand = self.db.epochs_demand()
        if not epochs_demand:
            logger.info({"msg": "No epoch demands found"})
        for consumer, (l_epoch, r_epoch, updated_at) in epochs_demand.items():
            logger.info({
                "msg": "Epochs demand", "consumer": consumer, "l_epoch": l_epoch, "r_epoch": r_epoch, "updated_at": updated_at
            })
            start_epoch = min(start_epoch, l_epoch)

        missing_epochs = self.db.missing_epochs_in(start_epoch, end_epoch)
        if missing_epochs:
            start_epoch = min(missing_epochs)
        else:
            # Start from the next epoch after the last epoch in the DB.
            start_epoch = EpochNumber(max_epoch_in_db + 1)

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
        max_updated_at = 0
        epochs_demand = self.db.epochs_demand()
        for _, (_, _, updated_at) in epochs_demand.items():
            max_updated_at = max(max_updated_at, updated_at)
        return max_updated_at
