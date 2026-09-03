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
    """The three points a report is built on.

    `ref_slot` labels the report on-chain, `slot_number` and `state_root` address the beacon state
    it reads, and the `block_*` fields address the execution block it reads.

    A slot's payload, deposits and withdrawals reach the beacon state when its *child* block is
    processed, so the report is built from `ref_slot`'s child, anchored on the last execution block
    that child's state has applied:

                            ref_slot
        slot      1      2      3      4      5
        cl       [x]    [ ]    [x]    [ ]    [x]
        el       [1]    [ ]    [ ]    [ ]    [2]

    `ref_slot` 3, `slot_number` 5, `block_number` 1: slot 3 withheld its payload, so EL block 1 is
    still the last one applied. Revealed, it would have been slot 3's own execution block.

    `slot_number` therefore exceeds `ref_slot` and addresses a different block than `block_number`.
    Ref slots are the last slot of an epoch, so `epoch_of(slot_number)` is normally `ref_epoch + 1`:
    read `ref_epoch` for the report's epoch, never `slot_number`.

    Before EIP-7732 all three are one block, falling back to the last non-missed slot at or before
    `ref_slot`.
    """

    ref_slot: SlotNumber
    ref_epoch: EpochNumber


class StakingModuleType(StrEnum):
    CURATED_ONCHAIN_V1_TYPE = 'curated-onchain-v1'
    COMMUNITY_ONCHAIN_V1_TYPE = 'community-onchain-v1'
    COMMUNITY_ONCHAIN_DEVNET0_V1_TYPE = 'community-staking-module'
    CURATED_ONCHAIN_V2_TYPE = 'curated-onchain-v2'
