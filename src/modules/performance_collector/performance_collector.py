import logging
from typing import Optional

from src.modules.performance_collector.checkpoint import (
    FrameCheckpointsIterator,
    FrameCheckpointProcessor,
    MinStepIsNotReached,
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

        db_min_unprocessed_epoch = self.db.min_unprocessed_epoch()
        start_epoch = EpochNumber(
            max(db_min_unprocessed_epoch, variables.PERFORMANCE_COLLECTOR_SERVER_START_EPOCH)
        )
        end_epoch = variables.PERFORMANCE_COLLECTOR_SERVER_END_EPOCH
        # TODO: adjust range by incoming POST requests

        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(last_finalized_blockstamp.slot_number) - 1)

        try:
            checkpoints = FrameCheckpointsIterator(
                converter,
                start_epoch,
                end_epoch,
                finalized_epoch,
            )
        except MinStepIsNotReached:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        processor = FrameCheckpointProcessor(self.w3.cc, self.db, converter, last_finalized_blockstamp)

        for checkpoint in checkpoints:
            processor.exec(checkpoint)
            # Reset BaseOracle cycle timeout to avoid timeout errors during long checkpoints processing
            self._reset_cycle_timeout()

        return ModuleExecuteDelay.NEXT_SLOT
