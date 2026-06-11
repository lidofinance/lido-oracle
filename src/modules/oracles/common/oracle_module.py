import logging
import traceback
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import TimeoutError as DecoratorTimeoutError
from web3.exceptions import Web3Exception
from web3_multi_provider import NoActiveProviderError

from src.modules.common.daemon_module import DaemonModule
from src.modules.oracles.common.consensus import ConsensusModule
from src.modules.oracles.common.exceptions import (
    ContractVersionMismatch,
    IncompatibleOracleVersion,
    IsNotMemberException,
)
from src.providers.consensus.client import ConsensusClient
from src.providers.http_provider import NotOkResponse
from src.providers.ipfs import IPFSError
from src.providers.keys.client import KAPIInconsistentData, KeysOutdatedException
from src.services.exit_order_iterator import WeightsNotUpdatedError
from src.types import BlockStamp
from src.utils.cache import clear_global_cache
from src.utils.slot import InconsistentData, NoSlotsAvailable, SlotNotFinalized
from src.web3py.extensions.lido_validators import CountOfKeysDiffersException
from src.web3py.types import Web3Base


logger = logging.getLogger(__name__)

W3 = TypeVar("W3", bound=Web3Base)


class OracleModule[W3: Web3Base](DaemonModule, ConsensusModule[W3], ABC):
    """
    Base skeleton for Oracle modules.

    Goals:
    - Catch errors and log them.
    - Raise exceptions that could not be proceeded automatically.
    - Check Module didn't stick inside cycle forever.
    """

    def __init__(self, w3: W3):
        super().__init__(w3=w3, cc=w3.cc)

    @property
    def cc(self) -> ConsensusClient:
        """Consensus client from w3"""
        return self.w3.cc

    def run_cycle(self, last_finalized_blockstamp: BlockStamp):
        """Override to add Oracle-specific logic before execution"""
        self.refresh_contracts_if_address_change()
        super().run_cycle(last_finalized_blockstamp)

    @contextmanager
    def exception_handler(self) -> Iterator[None]:  # noqa: C901
        # pylint: disable=too-many-branches
        """Context manager for handling Oracle module cycle exceptions"""
        try:
            yield
        except IsNotMemberException as error:
            logger.error({'msg': 'Provided account is not part of Oracle\'s committee.'})
            raise error
        except IncompatibleOracleVersion as error:
            logger.error({'msg': 'Incompatible Contract version. Please update Oracle Daemon.'})
            raise error
        except ContractVersionMismatch as error:
            logger.error(
                {
                    'msg': 'The oracle can\'t submit a report, because the contract\'s consensus version has changed.',
                    'error': str(error),
                }
            )
        except DecoratorTimeoutError as error:
            logger.error({'msg': 'Oracle module do not respond.', 'error': str(error)})
        except NoActiveProviderError as error:
            logger.error({'msg': ''.join(traceback.format_exception(error))})
        except RequestsConnectionError as error:
            logger.error({'msg': 'Connection error.', 'error': str(error)})
        except NotOkResponse as error:
            logger.error({'msg': ''.join(traceback.format_exception(error))})
        except (NoSlotsAvailable, SlotNotFinalized, InconsistentData) as error:
            logger.error({'msg': 'Inconsistent response from consensus layer node.', 'error': str(error)})
        except KAPIInconsistentData as error:
            logger.error({'msg': 'Inconsistent response from Keys API service', 'error': str(error)})
        except KeysOutdatedException as error:
            logger.error({'msg': 'Keys API service returns outdated data.', 'error': str(error)})
        except CountOfKeysDiffersException as error:
            logger.error({'msg': 'Keys API service returned incorrect number of keys.', 'error': str(error)})
        except WeightsNotUpdatedError as error:
            logger.error(
                {'msg': 'Staking module weights are not updated. Waiting for the next frame.', 'error': str(error)}
            )
        except Web3Exception as error:
            logger.error({'msg': 'Web3py exception.', 'error': str(error)})
        except IPFSError as error:
            logger.error({'msg': 'IPFS provider error.', 'error': str(error)})
        except ValueError as error:
            logger.error({'msg': 'Unexpected error.', 'error': str(error)})

    @abstractmethod
    def refresh_contracts(self):
        """This method called if contracts addresses were changed"""

    @abstractmethod
    def is_contracts_addresses_changed(self) -> bool:
        """Return True if underlying contracts addresses changed and refresh is needed."""

    def refresh_contracts_if_address_change(self):
        if self.is_contracts_addresses_changed():
            clear_global_cache()
            self.refresh_contracts()
