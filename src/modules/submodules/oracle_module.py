import logging
import time
from abc import abstractmethod, ABC
from dataclasses import asdict

from timeout_decorator import timeout
from src.web3_extentions.typings import Web3
from web3_multi_provider import NoActiveProviderError

from src import variables
from src.metrics.prometheus.basic import EXCEPTIONS_COUNT
from src.typings import SlotNumber, StateRoot, BlockHash, BlockStamp, BlockNumber, BlockRoot

logger = logging.getLogger(__name__)


# Sleep before new cycle begins
DEFAULT_SLEEP = 15


class BaseModule(ABC):
    """
    Base sceleton for Oracle modules.

    Goals:
    - Catch errors and log them.
    - Raise exceptions that could not be proceeded automatically.
    - Check Module didn't stick inside cycle forever.

    One cycle flow:
    - Fetch last checkpoint
    - If current_finalized_epoch > last_finalized_epoch: execute module
    - else: sleep and start over
    """
    _previous_finalized_slot_number = SlotNumber(0)

    def __init__(self, w3: Web3):
        self.w3 = w3

    def run_as_daemon(self):
        logger.info({'msg': '[Accounting] Run as daemon.'})
        while True:
            logger.info({'msg': 'Startup new cycle.'})
            self._cycle_handler()

    @timeout(variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
    def _cycle_handler(self):
        blockstamp = self._receive_last_finalized_slot()

        if blockstamp.slot_number > self._previous_finalized_slot_number:
            logger.info({'msg': 'New finalized block found.'})
            self._previous_finalized_slot_number = blockstamp.slot_number
            self.run_cycle(blockstamp)
        else:
            logger.info({'msg': f'No updates. Sleep for {DEFAULT_SLEEP}.'})
            time.sleep(DEFAULT_SLEEP)

    def _receive_last_finalized_slot(self) -> BlockStamp:
        block_root = BlockRoot(self.w3.cc.get_block_root('finalized').root)
        slot_details = self.w3.cc.get_block_details(block_root)

        state_root = StateRoot(slot_details.message.state_root)
        slot_number = SlotNumber(int(slot_details.message.slot))

        # Get EL block data
        execution_payload = slot_details.message.body['execution_payload']
        block_hash = BlockHash(execution_payload['block_hash'])
        block_number = BlockNumber(int(execution_payload['block_number']))

        bs = BlockStamp(
            block_root=block_root,
            state_root=state_root,
            slot_number=slot_number,
            block_hash=block_hash,
            block_number=block_number,
        )

        logger.info({'msg': 'Fetch last finalized BlockStamp.', 'value': asdict(bs)})

        return bs

    def run_cycle(self, blockstamp: BlockStamp):
        logger.info({'msg': 'Execute module.'})
        try:
            self.execute_module(blockstamp)
        except TimeoutError as exception:
            logger.error({"msg": "Price balancer do not respond.", "error": str(exception)})
            raise TimeoutError("Price balancer stuck.") from exception
        except NoActiveProviderError as exception:
            logger.error({'msg': 'No active node available.', 'error': str(exception)})
            raise NoActiveProviderError from exception
        except ConnectionError as error:
            logger.error({"msg": error.args, "error": str(error)})
            raise ConnectionError from error
        except ValueError as error:
            logger.error({"msg": error.args, "error": str(error)})
            time.sleep(DEFAULT_SLEEP)
            EXCEPTIONS_COUNT.labels(self.__class__.__name__).inc()
        except Exception as error:
            logger.error({"msg": f"Unexpected exception. Sleep for {DEFAULT_SLEEP}.", "error": str(error)})
            time.sleep(DEFAULT_SLEEP)
            EXCEPTIONS_COUNT.labels(self.__class__.__name__).inc()
        else:
            time.sleep(DEFAULT_SLEEP)

    @abstractmethod
    def execute_module(self, blockstamp: BlockStamp):
        """Implement module business logic here."""
        raise NotImplementedError('Module should implement this method.')
