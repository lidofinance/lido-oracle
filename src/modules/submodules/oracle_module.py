import logging
import time
from abc import abstractmethod, ABC
from dataclasses import asdict

from timeout_decorator import timeout

from src.modules.submodules.exceptions import IsNotMemberException, IncompatibleContractVersion
from src.providers.http_provider import NotOkResponse
from src.providers.keys.client import KeysOutdatedException
from src.utils.blockstamp import build_blockstamp
from src.utils.slot import NoSlotsAvailable, SlotNotFinalized, InconsistentData
from src.web3py.typings import Web3
from web3_multi_provider import NoActiveProviderError

from src import variables
from src.typings import SlotNumber, BlockStamp, BlockRoot


logger = logging.getLogger(__name__)


class BaseModule(ABC):
    """
    Base skeleton for Oracle modules.

    Goals:
    - Catch errors and log them.
    - Raise exceptions that could not be proceeded automatically.
    - Check Module didn't stick inside cycle forever.
    """
    DEFAULT_SLEEP = 12
    # This is reference mark for long sleep. Sleep until new finalized slot found.
    _slot_threshold = SlotNumber(0)

    def __init__(self, w3: Web3):
        self.w3 = w3

    def run_as_daemon(self):
        logger.info({'msg': 'Run module as daemon.'})
        while True:
            logger.info({'msg': 'Startup new cycle.'})
            self._cycle_handler()

    @timeout(variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
    def _cycle_handler(self):
        blockstamp = self._receive_last_finalized_slot()

        if blockstamp.slot_number > self._slot_threshold:
            sleep_for_this_finalized_epoch = self.run_cycle(blockstamp)

            if sleep_for_this_finalized_epoch:
                self._slot_threshold = blockstamp.slot_number

        logger.info({'msg': f'Cycle end. Sleep for {self.DEFAULT_SLEEP} seconds.'})
        time.sleep(self.DEFAULT_SLEEP)

    def _receive_last_finalized_slot(self) -> BlockStamp:
        block_root = BlockRoot(self.w3.cc.get_block_root('finalized').root)
        block_details = self.w3.cc.get_block_details(block_root)
        bs = build_blockstamp(block_details)
        logger.info({'msg': 'Fetch last finalized BlockStamp.', 'value': asdict(bs)})
        return bs

    def run_cycle(self, blockstamp: BlockStamp) -> bool:
        logger.info({'msg': 'Execute module.', 'value': blockstamp})

        try:
            return self.execute_module(blockstamp)
        except IsNotMemberException as exception:
            logger.error({'msg': 'Provided account is not part of Oracle`s committee.'})
            raise exception from exception
        except IncompatibleContractVersion as exception:
            logger.error({'msg': 'Incompatible Contract version. Please update Oracle Daemon.'})
            raise exception from exception
        except TimeoutError as exception:
            logger.error({'msg': 'Oracle module do not respond.', 'error': str(exception)})
        except NoActiveProviderError as exception:
            logger.error({'msg': 'No active node available.', 'error': str(exception)})
        except ConnectionError as error:
            logger.error({'msg': error.args, 'error': str(error)})
        except NotOkResponse as error:
            logger.error({'msg': 'Received non-ok response.', 'error': str(error)})
        except (NoSlotsAvailable, SlotNotFinalized, InconsistentData) as error:
            logger.error({'msg': 'Inconsistent response from consensus layer node.', 'error': str(error)})
        except KeysOutdatedException as error:
            logger.error({'msg': 'Keys API service returns outdated data.', 'error': str(error)})

        return False

    @abstractmethod
    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> bool:
        """
        Implement module business logic here.
        Return
            True - to sleep until new finalized epoch
            False - to sleep for a slot
        """
        raise NotImplementedError('Module should implement this method.')
