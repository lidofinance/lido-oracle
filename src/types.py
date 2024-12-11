from dataclasses import dataclass
from enum import StrEnum
from typing import NewType, List

from eth_typing import BlockNumber, ChecksumAddress, HexStr
from web3.types import Timestamp, Wei


class OracleModule(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'
    CHECK = 'check'
    CSM = 'csm'


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

Gwei = NewType('Gwei', int)

ValidatorIndex = NewType('ValidatorIndex', int)
CommitteeIndex = NewType('CommitteeIndex', int)

FinalizationBatches = NewType('FinalizationBatches', list[int])
WithdrawalVaultBalance = NewType('WithdrawalVaultBalance', Wei)
ELVaultBalance = NewType('ELVaultBalance', Wei)

type OperatorsValidatorCount = dict[NodeOperatorGlobalIndex, int]


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

@dataclass(frozen=True)
class ReportValues:
    timestamp: int
    time_elapsed: int
    cl_validators: int
    cl_balance: int
    withdrawal_vault_balance: int
    el_rewards_vault_balance: int
    shares_requested_to_burn: int
    withdrawal_finalization_batches: List[int]
    vault_values: List[int]
    net_cash_flows: List[int]