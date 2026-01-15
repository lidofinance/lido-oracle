import logging
import signal
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import ContextManager

from timeout_decorator import timeout

from src import variables
from src.metrics.healthcheck_server import pulse
from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.modules.common.types import ModuleExecuteDelay
from src.types import BlockStamp, BlockRoot, SlotNumber
from src.utils.blockstamp import build_blockstamp

logger = logging.getLogger(__name__)


class DaemonModule(ABC):
    """
    Base class for daemon-like modules.

    Provides common functionality for:
    - Running in daemon mode
    - Cycle handling
    - Getting last finalized slot
    - Timeout management
    """

    _slot_threshold: SlotNumber = SlotNumber(0)

    def run_as_daemon(self):
        """Starts module in daemon mode with infinite loop"""
        logger.info({'msg': 'Run module as daemon.'})
        while True:
            logger.debug({'msg': 'Startup new cycle.'})
            self.cycle_handler()

    def cycle_handler(self):
        """Handles one daemon module cycle"""
        self._cycle()
        self._sleep_cycle()

    @timeout(variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
    def _cycle(self):
        """
        Main cycle logic: gets last finalized slot and executes module business logic
        """
        with self.exception_handler():
            blockstamp = self._receive_last_finalized_slot()

            if blockstamp.slot_number <= self._slot_threshold:
                logger.info({
                    'msg': 'Skipping the report. Waiting for new finalized slot.',
                    'slot_threshold': self._slot_threshold,
                })
                return

            self.run_cycle(blockstamp)

    @staticmethod
    def _reset_cycle_timeout():
        """Resets timeout timer for current cycle"""
        logger.info({'msg': f'Reset running cycle timeout to {variables.MAX_CYCLE_LIFETIME_IN_SECONDS} seconds'})
        signal.setitimer(signal.ITIMER_REAL, variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
        pulse()

    @staticmethod
    def _sleep_cycle():
        """Handles sleeping between cycles based on configured cycle sleep time"""
        logger.info({'msg': f'Cycle end. Sleeping for {variables.CYCLE_SLEEP_IN_SECONDS} seconds.'})
        time.sleep(variables.CYCLE_SLEEP_IN_SECONDS)

    def _receive_last_finalized_slot(self) -> BlockStamp:
        """Gets last finalized BlockStamp"""
        cc = self._get_consensus_client()
        block_root = BlockRoot(cc.get_block_root('finalized').root)
        block_details = cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)
        logger.info({'msg': 'Fetch last finalized BlockStamp.', 'value': asdict(bs)})
        ORACLE_SLOT_NUMBER.labels('finalized').set(bs.slot_number)
        ORACLE_BLOCK_NUMBER.labels('finalized').set(bs.block_number)
        return bs

    def run_cycle(self, last_finalized_blockstamp: BlockStamp):
        """Base logic for daemon module cycle execution"""
        logger.info({'msg': 'Execute module.', 'value': last_finalized_blockstamp})
        result = self.execute_module(last_finalized_blockstamp)
        pulse()
        if result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH:
            self._slot_threshold = last_finalized_blockstamp.slot_number

    @abstractmethod
    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        """Executes module business logic for given blockstamp"""

    @abstractmethod
    def _get_consensus_client(self):
        """Returns consensus client for blockchain data access"""

    @abstractmethod
    def exception_handler(self) -> ContextManager[None]:
        """Context manager for cycle exception handling"""
