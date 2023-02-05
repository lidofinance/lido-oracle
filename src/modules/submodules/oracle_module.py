import logging
import time
from abc import abstractmethod, ABC

from timeout_decorator import timeout
from web3_multi_provider import NoActiveProviderError

from src import variables, constants
from src.metrics.prometheus.basic import EXCEPTIONS_COUNT
from src.modules.submodules.provider import ProviderModule
from src.typings import SlotNumber, StateRoot, BlockHash, BlockStamp, BlockNumber

logger = logging.getLogger(__name__)


class OracleModule(ProviderModule, ABC):
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

    def run_as_daemon(self):
        while True:
            self._cycle_handler()

    @timeout(variables.MAX_CYCLE_LIFETIME_IN_SECONDS)
    def _cycle_handler(self):
        blockstamp = self._receive_last_finalized_slot()

        if blockstamp['slot_number'] > self._previous_finalized_slot_number:
            self._previous_finalized_epoch = blockstamp['slot_number']
            self.run_cycle(blockstamp)

    def _receive_last_finalized_slot(self) -> BlockStamp:
        slot_root = StateRoot(self._cc.get_block_root('finalized')['root'])
        slot_details = self._cc.get_block_details(slot_root)
        slot_number = SlotNumber(int(slot_details['message']['slot']))
        # Get EL block data
        execution_payload = self._cc.get_block_details(slot_root)['message']['body']['execution_payload']
        block_hash = BlockHash(execution_payload['block_hash'])
        block_number = BlockNumber(int(execution_payload['block_number']))
        return BlockStamp(
            state_root=slot_root,
            slot_number=slot_number,
            block_hash=block_hash,
            block_number=block_number,
        )

    def run_cycle(self, blockstamp: BlockStamp):
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
            time.sleep(constants.DEFAULT_SLEEP)
            EXCEPTIONS_COUNT.labels(self.__class__.__name__).inc()
        except Exception as error:
            logger.warning({"msg": "Unexpected exception.", "error": str(error)})
            time.sleep(constants.DEFAULT_SLEEP)
            EXCEPTIONS_COUNT.labels(self.__class__.__name__).inc()
        else:
            time.sleep(constants.DEFAULT_SLEEP)

    @abstractmethod
    def execute_module(self, blockstamp: BlockStamp):
        """Implement module business logic here."""
        raise NotImplementedError('Module should implement this method.')
