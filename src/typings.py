from enum import Enum, StrEnum
from typing import TypedDict, NewType

from hexbytes import HexBytes


class Module(StrEnum):
    ACCOUNTING = 'accounting'
    EJECTOR = 'ejector'


EpochNumber = NewType('EpochNumber', int)

StateRoot = NewType('StateRoot', HexBytes)
SlotNumber = NewType('SlotNumber', int)

BlockHash = NewType('BlockHash', HexBytes)
BlockNumber = NewType('BlockNumber', int)


class BlockStamp(TypedDict):
    state_root: StateRoot
    slot_number: SlotNumber
    block_hash: BlockHash
    block_number: BlockNumber


# ---- review -----
# class ValidatorGroup:
#     PENDING = [
#         ValidatorStatus.PENDING_INITIALIZED,
#         ValidatorStatus.PENDING_QUEUED,
#     ]
#
#     ACTIVE = [
#         ValidatorStatus.ACTIVE_ONGOING,
#         ValidatorStatus.ACTIVE_EXITING,
#         ValidatorStatus.ACTIVE_SLASHED,
#     ]
#
#     EXITED = [
#         ValidatorStatus.EXITED_UNSLASHED,
#         ValidatorStatus.EXITED_SLASHED,
#     ]
#
#     WITHDRAWAL = [
#         ValidatorStatus.WITHDRAWAL_POSSIBLE,
#         ValidatorStatus.WITHDRAWAL_DONE,
#     ]
#
#     # Used to calculate balance for ejection
#     GOING_TO_EXIT = [
#         ValidatorStatus.ACTIVE_EXITING,
#         ValidatorStatus.ACTIVE_SLASHED,
#         ValidatorStatus.EXITED_SLASHED,
#         ValidatorStatus.EXITED_UNSLASHED,
#         ValidatorStatus.WITHDRAWAL_POSSIBLE,
#     ]
# # class ModifiedOperator(Operator):
# class ModifiedOperator():
#     """TODO: Remove as soon as lido_sdk will support module_id"""
#     module_id: str
#
#
# # class ModifiedOperatorKey(OperatorKey):
# class ModifiedOperatorKey():
#     """TODO: Remove as soon as lido_sdk will support module_id"""
#     module_id: str
#
#
# class MergedLidoValidator(TypedDict):
#     validator: Validator
#     key: ModifiedOperatorKey
