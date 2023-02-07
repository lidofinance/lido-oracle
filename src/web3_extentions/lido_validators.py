from functools import lru_cache
from typing import List, Dict, Tuple, TypedDict

from eth_typing import Address
from web3.module import Module

from src.providers.consensus.typings import Validator
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


class LidoValidatorsProvider(Module):
    @lru_cache(maxsize=1)
    def get_lido_validators(self, blockstamp: BlockStamp) -> List[LidoValidator]:
        lido_keys = self.w3.kac.get_all_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp['state_root'])

        return self._merge_validators(lido_keys, validators)

    @staticmethod
    def _merge_validators(keys: List[LidoKey], validators: List[Validator]) -> List[LidoValidator]:
        """Merging and filter non-lido validators."""
        validators_keys_dict = {validator['validator']['pubkey']: validator for validator in validators}

        lido_validators = []

        for key in keys:
            lido_validators.append(LidoValidator(
                key=key,
                validator=validators_keys_dict[key['key']],
            ))

        return lido_validators

    @lru_cache(maxsize=1)
    def get_lido_validators_by_node_operators(self, blockstamp: BlockStamp) -> Dict[NodeOperatorIndex, LidoValidator]:
        pass

    @lru_cache(maxsize=1)
    def get_lido_node_operators(self, blockstamp: BlockStamp) -> List[NodeOperator]:
        pass
