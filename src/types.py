from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from eth_typing import BlockNumber, ChecksumAddress, HexStr
from web3.types import Timestamp, Wei


class OracleModuleName(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'
    CHECK = 'check'
    CSM = 'csm'
    CM = 'cm'
    PERFORMANCE_WEB_SERVER = 'performance_web_server'
    PERFORMANCE_COLLECTOR = 'performance_collector'


EpochNumber = NewType('EpochNumber', int)
FrameNumber = NewType('FrameNumber', int)
StateRoot = NewType('StateRoot', HexStr)
BlockRoot = NewType('BlockRoot', HexStr)
SlotNumber = NewType('SlotNumber', int)

StakingModuleAddress = NewType('StakingModuleAddress', ChecksumAddress)
StakingModuleId = NewType('StakingModuleId', int)
NodeOperatorId = NewType('NodeOperatorId', int)
NodeOperatorGlobalIndex = tuple[StakingModuleId, NodeOperatorId]

BlockHash = NewType('BlockHash', HexStr)


class Gwei(int):
    """Gwei type with addition support."""

    def __add__(self, other) -> Gwei:
        if isinstance(other, (int, Gwei)):
            return Gwei(int.__add__(self, int(other)))
        return NotImplemented

    def __radd__(self, other) -> Gwei:
        if isinstance(other, (int, Gwei)):
            return Gwei(int.__add__(int(other), self))
        return NotImplemented

    def __sub__(self, other) -> Gwei:
        if isinstance(other, (int, Gwei)):
            return Gwei(int.__sub__(self, int(other)))
        return NotImplemented

    def __rsub__(self, other) -> Gwei:
        if isinstance(other, (int, Gwei)):
            return Gwei(int.__sub__(int(other), self))
        return NotImplemented


ValidatorIndex = NewType('ValidatorIndex', int)
CommitteeIndex = NewType('CommitteeIndex', int)

FinalizationBatches = NewType('FinalizationBatches', list[int])
WithdrawalVaultBalance = NewType('WithdrawalVaultBalance', Wei)
ELVaultBalance = NewType('ELVaultBalance', Wei)

type OperatorsValidatorCount = dict[NodeOperatorGlobalIndex, int]
type OperatorsBalance = dict[NodeOperatorGlobalIndex, Wei]


@dataclass(frozen=True)
class BlockStamp:
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber
    block_timestamp: Timestamp


@dataclass(frozen=True)
class ReferenceBlockStamp(BlockStamp):
    # Ref slot could differ from slot_number if ref_slot was missed slot_number will be previous first non-missed slot
    ref_slot: SlotNumber
    ref_epoch: EpochNumber

    # Glamsterdam/EIP-7732 fields. All default to a pre-fork-shaped value so nothing changes
    # before Gloas is active. Post-fork, the execution payload of `ref_slot`'s own block is no
    # longer guaranteed to be present, so the execution-layer anchor (block_hash/number/timestamp
    # above) and pending_deposits are resolved from `ref_slot`'s child block instead. See
    # src/utils/blockstamp.py and the Glamsterdam LIP for the full rationale.
    #
    # State root and slot of the child (first non-missed block after this report's own block).
    # pending_deposits are read from this state, not from this block's own state, because a
    # slot's deposits are only merged into pending_deposits once its child is processed.
    child_state_root: StateRoot | None = None
    child_slot: SlotNumber | None = None
    # True when ref_slot's own execution payload was not confirmed full by the time its child
    # was processed. In that case CL balances are already reduced by payload_expected_withdrawals
    # while the execution layer has not yet credited them, so the Accounting Oracle must add them
    # back (see src/utils/validator_balance.py::gloas_balance_correction).
    withdrawal_correction_needed: bool = False


class StakingModuleType(StrEnum):
    CURATED_ONCHAIN_V1_TYPE = 'curated-onchain-v1'
    COMMUNITY_ONCHAIN_V1_TYPE = 'community-onchain-v1'
    COMMUNITY_ONCHAIN_DEVNET0_V1_TYPE = 'community-staking-module'
    CURATED_ONCHAIN_V2_TYPE = 'curated-onchain-v2'
