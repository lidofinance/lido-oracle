from functools import lru_cache
from typing import List, Dict, Tuple, TypedDict

from eth_typing import Address
from web3 import Web3

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.typings import Validator
from src.providers.keys.client import KeysAPIClient
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp


class LidoValidator(TypedDict):
    key: LidoKey
    validator: Validator


class NodeOperator(TypedDict):
    # Flag indicating if the operator can participate in further staking and reward distribution
    active: bool
    # Ethereum address on Execution Layer which receives steth rewards for this operator
    rewardAddress: Address
    # Human-readable name
    name: str

    """
    /// @dev The below variables store the signing keys info of the node operator.
    ///     These variables can take values in the following ranges:
    ///
    ///                0             <=  exitedSigningKeysCount   <= depositedSigningKeysCount
    ///     exitedSigningKeysCount   <= depositedSigningKeysCount <=  vettedSigningKeysCount
    ///    depositedSigningKeysCount <=   vettedSigningKeysCount  <=   totalSigningKeysCount
    ///    depositedSigningKeysCount <=   totalSigningKeysCount   <=        MAX_UINT64
    ///
    /// Additionally, the exitedSigningKeysCount and depositedSigningKeysCount values are monotonically increasing:
    /// :                              :         :         :         :
    /// [....exitedSigningKeysCount....]-------->:         :         :
    /// [....depositedSigningKeysCount :.........]-------->:         :
    /// [....vettedSigningKeysCount....:.........:<--------]-------->:
    /// [....totalSigningKeysCount.....:.........:<--------:---------]------->
    /// :                              :         :         :         :
    """
    # Maximum number of keys for this operator to be deposited for all time
    vettedSigningKeysCount: int
    # Number of keys in the EXITED state for this operator for all time
    exitedSigningKeysCount: int
    # Total number of keys of this operator for all time
    totalSigningKeysCount: int
    # Number of keys of this operator which were in DEPOSITED state for all time
    depositedSigningKeysCount: int


NodeOperatorIndex = Tuple[Address, int]


class LidoValidatorsService:
    def __init__(self, web3: Web3, cc: ConsensusClient, kac: KeysAPIClient):
        self._w3 = web3
        self._cc = cc
        self._kac = kac

    @lru_cache(maxsize=1)
    def get_lido_validators(self, blockstamp: BlockStamp) -> List[LidoValidator]:
        lido_keys = self._kac.get_all_lido_keys(blockstamp)
        validators = self._cc.get_validators(blockstamp['state_root'])

        pass



    def _merge_validators(self, keys: List[LidoKey], validators: List[Validator]):
        pass

    @lru_cache(maxsize=1)
    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> Dict[NodeOperatorIndex, LidoValidator]:
        pass

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> List[NodeOperator]:
        pass
