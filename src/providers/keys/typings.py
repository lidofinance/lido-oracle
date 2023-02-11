from dataclasses import dataclass

from eth_typing import Address
from hexbytes import HexBytes

from src.utils.dataclass import Nested


@dataclass
class LidoKey:
    key: HexBytes
    depositSignature: HexBytes
    operatorIndex: int
    used: bool
    moduleAddress: Address


@dataclass
class Operator:
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


@dataclass
class OperatorExpanded(Operator):
    stakingModuleAddress: Address


@dataclass
class ContractModule:
    nonce: int
    type: str
    id: int
    stakingModuleAddress: Address
    name: str

    # moduleFee: int
    # treasuryFee: int
    # targetShare: int
    # status: int
    # lastDepositAt: int
    # lastDepositBlock: int


@dataclass
class OperatorResponse(Nested):
    operators: list[Operator]
    module: ContractModule
