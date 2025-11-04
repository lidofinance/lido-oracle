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
from src.utils.range import sequence
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

        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(last_finalized_blockstamp.slot_number) - 1)

        epochs_range = self.define_epochs_to_process_range(finalized_epoch)
        if not epochs_range:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
        start_epoch, end_epoch = epochs_range

        min_unprocessed_epoch = min(self.db.missing_epochs_in(start_epoch, end_epoch), default=None)
        if not min_unprocessed_epoch:
            raise ValueError("There should be at least one epoch to process.")

        logger.info({
            'msg': 'Starting epoch range processing',
            "start_epoch": start_epoch,
            "end_epoch": end_epoch,
            "min_unprocessed_epoch": min_unprocessed_epoch,
            "finalized_epoch": finalized_epoch
        })

        try:
            checkpoints = FrameCheckpointsIterator(
                converter,
                EpochNumber(min_unprocessed_epoch),
                end_epoch,
                finalized_epoch,
            )
        except MinStepIsNotReached:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        processor = FrameCheckpointProcessor(self.w3.cc, self.db, converter, last_finalized_blockstamp)

        checkpoint_count = 0
        for checkpoint in checkpoints:
            curr_finalized_slot = self._receive_last_finalized_slot()
            curr_finalized_epoch = EpochNumber(converter.get_epoch_by_slot(curr_finalized_slot.slot_number) - 1)
            new_epochs_range = self.define_epochs_to_process_range(curr_finalized_epoch, log=False)
            if new_epochs_range:
                new_start_epoch, new_end_epoch = new_epochs_range
                if new_start_epoch != start_epoch or new_end_epoch != end_epoch:
                    logger.info({
                        "msg": "New epochs range to process is found, stopping current epochs range processing"
                    })
                    return ModuleExecuteDelay.NEXT_SLOT

            processed_epochs = processor.exec(checkpoint)
            checkpoint_count += 1
            logger.info({
                'msg': 'Checkpoint processing completed',
                'checkpoint_slot': checkpoint.slot,
                'processed_epochs': processed_epochs
            })
            # Reset BaseOracle cycle timeout to avoid timeout errors during long checkpoints processing
            self._reset_cycle_timeout()

        logger.info({
            'msg': 'All checkpoints processing completed',
            'total_checkpoints_processed': checkpoint_count
        })

        return ModuleExecuteDelay.NEXT_SLOT

    def define_epochs_to_process_range(self, finalized_epoch: EpochNumber, log=True) -> tuple[EpochNumber, EpochNumber] | None:
        unsatisfied_demands = []
        epochs_demand = self.db.epochs_demand()
        for consumer, (l_epoch, r_epoch) in epochs_demand.items():
            if log:
                logger.info({
                    "msg": "Epochs demand is found",
                    "consumer": consumer,
                    "l_epoch": l_epoch,
                    "r_epoch": r_epoch
                })
            satisfied = self.db.is_range_available(l_epoch, r_epoch)
            if satisfied:
                if log:
                    logger.info({
                        "msg": "Epochs demand is already satisfied, skipping",
                        "start_epoch": l_epoch,
                        "end_epoch": r_epoch
                    })
                continue
            unsatisfied_demands.append((consumer, l_epoch, r_epoch))

        if not unsatisfied_demands:
            if log:
                logger.info({'msg': 'No epochs demand to process, waiting for any next demand'})
            return None

        faced_deadline = []
        for consumer, l_epoch, r_epoch in unsatisfied_demands:
            if finalized_epoch >= r_epoch:
                if log:
                    logger.warning({
                        "msg": "Epochs demand is passed deadline due to current finalized epoch",
                        "consumer": consumer,
                        "l_epoch": l_epoch,
                        "r_epoch": r_epoch,
                        "finalized_epoch": finalized_epoch
                    })
                faced_deadline.append((consumer, l_epoch, r_epoch))

        def missing_epochs(_, l_epoch_, r_epoch_):
            return self.db.missing_epochs_in(l_epoch_, r_epoch_)

        if not faced_deadline:
            unsatisfied_demands.sort(
                # Demand with the largest count of unprocessed epochs goes first
                key=lambda demand: (-1 * len(missing_epochs(*demand)))
            )
            consumer, start_epoch, end_epoch = unsatisfied_demands[0]
        else:
            faced_deadline.sort(
                # Demand with the least count of unprocessed epochs goes first
                key=lambda demand: len(missing_epochs(*demand))
            )
            consumer, start_epoch, end_epoch = faced_deadline[0]

        if log:
            logger.info({
                "msg": "Epochs demand is chosen to process",
                "consumer": consumer,
                "start_epoch": start_epoch,
                "end_epoch": end_epoch,
            })

        return start_epoch, end_epoch
