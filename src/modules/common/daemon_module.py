import logging
import signal
import time
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager

from timeout_decorator import timeout
from web3.eth import Eth

from src import variables
from src.metrics.healthcheck_server import pulse
from src.metrics.prometheus.basic import (
    CYCLE_COUNT,
    LAST_CYCLE_TIMESTAMP,
    CycleResult,
)
from src.modules.common.types import ModuleExecuteDelay
from src.providers.consensus.client import ConsensusClient
from src.types import BlockStamp, SlotNumber
from src.utils.blockstamp import get_blockstamp_by_state


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

    def __init__(self, cc: ConsensusClient, el: Eth | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cc = cc
        # Optional execution client. Needed post-EIP-7732 to resolve the execution anchor of the
        # finalized liveness blockstamp (a block's own execution payload is no longer embedded).
        # CL-only daemons (the performance collector) leave this None and never read EL fields.
        self._el = el
        self._slot_threshold = SlotNumber(0)

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
        cycle_result = CycleResult.ERROR
        try:
            with self.exception_handler():
                blockstamp = self._receive_last_finalized_slot()

                if blockstamp.slot_number <= self._slot_threshold:
                    logger.info(
                        {
                            'msg': 'Skipping the report. Waiting for new finalized slot.',
                            'slot_threshold': self._slot_threshold,
                        }
                    )
                    cycle_result = CycleResult.SUCCESS
                    return

                self.run_cycle(blockstamp)
                cycle_result = CycleResult.SUCCESS
        finally:
            CYCLE_COUNT.labels(result=cycle_result.value).inc()
            LAST_CYCLE_TIMESTAMP.labels(result=cycle_result.value).set(time.time())

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
        return get_blockstamp_by_state(self.cc, 'finalized', el=self._el)

    def run_cycle(self, last_finalized_blockstamp: BlockStamp):
        """Base logic for daemon module cycle execution"""
        logger.info({'msg': 'Execute module.', 'value': last_finalized_blockstamp})
        result = self.execute_module(last_finalized_blockstamp)
        pulse()
        if result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH:
            self._slot_threshold = last_finalized_blockstamp.slot_number

    @abstractmethod
    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        """Executes module business logic for a given blockstamp"""

    @property
    def cc(self) -> ConsensusClient:
        """Consensus client for blockchain data access"""
        return self._cc

    @abstractmethod
    def exception_handler(self) -> AbstractContextManager[None]:
        """Context manager for cycle exception handling"""
