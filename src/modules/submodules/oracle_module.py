import logging
import time
import traceback
from abc import abstractmethod, ABC
from dataclasses import asdict
from enum import Enum

from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import timeout, TimeoutError as DecoratorTimeoutError
from web3.exceptions import Web3Exception

from src.metrics.healthcheck_server import pulse
from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.modules.submodules.exceptions import IsNotMemberException, IncompatibleOracleVersion
from src.providers.http_provider import NotOkResponse
from src.providers.ipfs import IPFSError
from src.providers.keys.client import KeysOutdatedException
from src.utils.cache import clear_global_cache
from src.web3py.extensions.lido_validators import CountOfKeysDiffersException
from src.utils.blockstamp import build_blockstamp
from src.utils.slot import NoSlotsAvailable, SlotNotFinalized, InconsistentData
from src.web3py.types import Web3
from web3_multi_provider import NoActiveProviderError

from src import variables
from src.types import SlotNumber, BlockStamp, BlockRoot

logger = logging.getLogger(__name__)


class ModuleExecuteDelay(Enum):
    """Signals from execute_module method"""
    NEXT_SLOT = 0
    NEXT_FINALIZED_EPOCH = 1


def _handle_error(error):
    """Handle exceptions and log messages based on exception type."""
    error_mapping = {
        IsNotMemberException: 'Provided account is not part of Oracle`s committee.',
        IncompatibleOracleVersion: 'Incompatible Contract version. Please update Oracle Daemon.',
        DecoratorTimeoutError: 'Oracle module do not respond.',
        NoActiveProviderError: 'No active provider available.',
        RequestsConnectionError: 'Connection error.',
        NotOkResponse: 'Invalid response from server.',
        (NoSlotsAvailable, SlotNotFinalized, InconsistentData): 'Inconsistent response from consensus layer node.',
        KeysOutdatedException: 'Keys API service returns outdated data.',
        CountOfKeysDiffersException: 'Keys API service returned incorrect number of keys.',
        Web3Exception: 'Web3py exception.',
        IPFSError: 'IPFS provider error.',
        ValueError: 'Unexpected error.',
    }

    for exception_type, message in error_mapping.items():
        if isinstance(error, exception_type):
            if isinstance(error, NotOkResponse):
                logger.error({'msg': ''.join(traceback.format_exception(error))})
                return
            # Reraise specific exceptions
            if isinstance(error, (IsNotMemberException, IncompatibleOracleVersion)):
                logger.error({'msg': message})
                raise error
            logger.error({'msg': message, 'error': str(error)})
            return  # Handled exception; no further action needed

    # Reraise unhandled exceptions
    raise error


class BaseModule(ABC):
    """
    Base skeleton for Oracle modules.

    Goals:
    - Catch errors and log them.
    - Raise exceptions that could not be proceeded automatically.
    - Check Module didn't stick inside cycle forever.
    """

    # This is reference mark for long sleep. Sleep until new finalized slot found.
    _slot_threshold = SlotNumber(0)

    def __init__(self, w3: Web3):
        self.w3 = w3

    def run_as_daemon(self):
        logger.info({'msg': 'Run module as daemon.'})
        while True:
            logger.debug({'msg': 'Startup new cycle.'})
            self.cycle_handler()

    def cycle_handler(self):
        self._cycle()
        self._sleep_cycle()

    @timeout(variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
    def _cycle(self):
        """
        Main cycle logic: fetch the last finalized slot, refresh contracts if necessary,
        and execute the module's business logic.
        """
        try:
            blockstamp = self._receive_last_finalized_slot()

            # Check if the blockstamp is below the threshold and exit early
            if blockstamp.slot_number <= self._slot_threshold:
                logger.info({
                    'msg': 'Skipping the report. Waiting for new finalized slot.',
                    'slot_threshold': self._slot_threshold,
                })
                return

            self.refresh_contracts_if_address_change()
            self.run_cycle(blockstamp)
        except Exception as exception:
            _handle_error(exception)

    @staticmethod
    def _sleep_cycle():
        """Handles sleeping between cycles based on the configured cycle sleep time."""
        logger.info({'msg': f'Cycle end. Sleeping for {variables.CYCLE_SLEEP_IN_SECONDS} seconds.'})
        time.sleep(variables.CYCLE_SLEEP_IN_SECONDS)

    def _receive_last_finalized_slot(self) -> BlockStamp:
        block_root = BlockRoot(self.w3.cc.get_block_root('finalized').root)
        block_details = self.w3.cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)
        logger.info({'msg': 'Fetch last finalized BlockStamp.', 'value': asdict(bs)})
        ORACLE_SLOT_NUMBER.labels('finalized').set(bs.slot_number)
        ORACLE_BLOCK_NUMBER.labels('finalized').set(bs.block_number)
        return bs

    def run_cycle(self, blockstamp: BlockStamp):
        logger.info({'msg': 'Execute module.', 'value': blockstamp})
        result = self.execute_module(blockstamp)
        pulse()
        if result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH:
            self._slot_threshold = blockstamp.slot_number

    @abstractmethod
    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        """
        Implement module business logic here.
        Return
            ModuleExecuteDelay.NEXT_FINALIZED_EPOCH - to sleep until new finalized epoch
            ModuleExecuteDelay.NEXT_SLOT - to sleep for a slot
        """
        raise NotImplementedError('Module should implement this method.')  # pragma: no cover

    @abstractmethod
    def refresh_contracts(self):
        """This method called if contracts addresses were changed"""
        raise NotImplementedError('Module should implement this method.')  # pragma: no cover

    def refresh_contracts_if_address_change(self):
        # Refresh contracts if the address has changed
        if self.w3.lido_contracts.has_contract_address_changed():
            clear_global_cache()
            self.refresh_contracts()
