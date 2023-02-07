from typing import TypedDict, List

from eth_typing import Address
from hexbytes import HexBytes


class LidoKey(TypedDict):
    key: HexBytes
    depositSignature: HexBytes
    operatorIndex: int
    used: bool
    moduleAddress: Address


class OperatorResponse(TypedDict):
    operators: List['Operator']
    module: 'ContractModule'


class Operator(TypedDict):
    index: int
    active: bool
    name: str
    rewardAddress: Address
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
    stakingLimit: int
    # Number of keys in the EXITED state for this operator for all time
    stoppedValidators: int
    # Total number of keys of this operator for all time
    totalSigningKeys: int
    # Number of keys of this operator which were in DEPOSITED state for all time
    usedSigningKeys: int


class ContractModule(TypedDict):
    nonce: int
    type: str
    id: str
    stakingModuleAddress: Address
    moduleFee: int
    treasuryFee: int
    targetShare: int
    status: int
    name: str
    lastDepositAt: int
    lastDepositBlock: int
