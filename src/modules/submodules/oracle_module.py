import logging
import time
from abc import abstractmethod, ABC
from dataclasses import asdict
from enum import Enum

from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import timeout, TimeoutError as DecoratorTimeoutError

from src.metrics.prometheus.basic import ORACLE_BLOCK_NUMBER, ORACLE_SLOT_NUMBER
from src.modules.submodules.exceptions import IsNotMemberException, IncompatibleContractVersion
from src.providers.http_provider import NotOkResponse
from src.providers.keys.client import KeysOutdatedException
from src.utils.cache import clear_global_cache
from src.web3py.extensions.lido_validators import CountOfKeysDiffersException
from src.utils.blockstamp import build_blockstamp
from src.utils.slot import NoSlotsAvailable, SlotNotFinalized, InconsistentData
from src.web3py.typings import Web3
from web3_multi_provider import NoActiveProviderError

from src import variables
from src.typings import SlotNumber, BlockStamp, BlockRoot


logger = logging.getLogger(__name__)


class ModuleExecuteDelay(Enum):
    """Signals from execute_module method"""
    NEXT_SLOT = 0
    NEXT_FINALIZED_EPOCH = 1


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
            logger.info({'msg': 'Startup new cycle.'})
            self.cycle_handler()

    @timeout(variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
    def cycle_handler(self):
        blockstamp = self._receive_last_finalized_slot()

        if blockstamp.slot_number > self._slot_threshold:
            if self.w3.lido_contracts.has_contract_address_changed():
                clear_global_cache()
                self.refresh_contracts()
            result = self.run_cycle(blockstamp)

            if result is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH:
                self._slot_threshold = blockstamp.slot_number
        else:
            logger.info({
                'msg': 'Skipping the report. Wait for new finalized slot.',
                'slot_threshold': self._slot_threshold,
            })

        logger.info({'msg': f'Cycle end. Sleep for {variables.CYCLE_SLEEP_IN_SECONDS} seconds.'})
        time.sleep(variables.CYCLE_SLEEP_IN_SECONDS)

    def _receive_last_finalized_slot(self) -> BlockStamp:
        block_root = BlockRoot(self.w3.cc.get_block_root('finalized').root)
        block_details = self.w3.cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)
        logger.info({'msg': 'Fetch last finalized BlockStamp.', 'value': asdict(bs)})
        ORACLE_SLOT_NUMBER.labels('finalized').set(bs.slot_number)
        ORACLE_BLOCK_NUMBER.labels('finalized').set(bs.block_number)
        return bs

    def run_cycle(self, blockstamp: BlockStamp) -> ModuleExecuteDelay:
        logger.info({'msg': 'Execute module.', 'value': blockstamp})

        try:
            return self.execute_module(blockstamp)
        except IsNotMemberException as exception:
            logger.error({'msg': 'Provided account is not part of Oracle`s committee.'})
            raise exception
        except IncompatibleContractVersion as exception:
            logger.error({'msg': 'Incompatible Contract version. Please update Oracle Daemon.'})
            raise exception
        except DecoratorTimeoutError as exception:
            logger.error({'msg': 'Oracle module do not respond.', 'error': str(exception)})
        except NoActiveProviderError as exception:
            logger.error({'msg': 'No active node available.', 'error': str(exception)})
        except RequestsConnectionError as error:
            logger.error({'msg': 'Connection error.', 'error': str(error)})
        except NotOkResponse as error:
            logger.error({'msg': 'Received non-ok response.', 'error': str(error)})
        except (NoSlotsAvailable, SlotNotFinalized, InconsistentData) as error:
            logger.error({'msg': 'Inconsistent response from consensus layer node.', 'error': str(error)})
        except KeysOutdatedException as error:
            logger.error({'msg': 'Keys API service returns outdated data.', 'error': str(error)})
        except CountOfKeysDiffersException as error:
            logger.error({'msg': 'Keys API service returned incorrect number of keys.', 'error': str(error)})
        except ValueError as error:
            logger.error({'msg': 'Unexpected error.', 'error': str(error)})

        return ModuleExecuteDelay.NEXT_SLOT

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
