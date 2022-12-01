from enum import Enum
from typing import TypedDict, List, Dict, NewType

from lido_sdk.methods.typing import OperatorKey


Epoch = NewType('Epoch', int)
Slot = NewType('Slot', int)


class ValidatorStatus(Enum):
    PENDING_INITIALIZED = 'pending_initialized'
    PENDING_QUEUED = 'pending_queued'

    ACTIVE_ONGOING = 'active_ongoing'
    ACTIVE_EXITING = 'active_exiting'
    ACTIVE_SLASHED = 'active_slashed'

    EXITED_UNSLASHED = 'exited_unslashed'
    EXITED_SLASHED = 'exited_slashed'

    WITHDRAWAL_POSSIBLE = 'withdrawal_possible'
    WITHDRAWAL_DONE = 'withdrawal_done'


class ValidatorGroup:
    PENDING = [
        ValidatorStatus.PENDING_INITIALIZED,
        ValidatorStatus.PENDING_QUEUED,
    ]

    ACTIVE = [
        ValidatorStatus.ACTIVE_ONGOING,
        ValidatorStatus.ACTIVE_EXITING,
        ValidatorStatus.ACTIVE_SLASHED,
    ]

    EXITED = [
        ValidatorStatus.EXITED_UNSLASHED,
        ValidatorStatus.EXITED_SLASHED,
    ]

    WITHDRAWAL = [
        ValidatorStatus.WITHDRAWAL_POSSIBLE,
        ValidatorStatus.WITHDRAWAL_DONE,
    ]

    # Used to calculate balance for ejection
    GOING_TO_EXIT = [
        ValidatorStatus.ACTIVE_EXITING,
        ValidatorStatus.ACTIVE_SLASHED,
        ValidatorStatus.EXITED_SLASHED,
        ValidatorStatus.EXITED_UNSLASHED,
        ValidatorStatus.WITHDRAWAL_POSSIBLE,
    ]


class Checkpoint(TypedDict):
    epoch: str
    root: str


class StateFinalityCheckpoints(TypedDict):
    previous_justified: Checkpoint
    current_justified: Checkpoint
    finalized: Checkpoint


class ValidatorState(TypedDict):
    pubkey: str
    withdrawal_credentials: str
    effective_balance: str
    slashed: bool
    activation_eligibility_epoch: bool
    activation_epoch: str
    exit_epoch: str
    withdrawable_epoch: str


class Validator(TypedDict):
    index: int
    balance: int
    status: ValidatorStatus
    validator: ValidatorState


class BlockMessage(TypedDict):
    slot: str
    proposer_index: str
    parent_root: str
    state_root: str
    body: dict


class SignedBeaconBlock(TypedDict):
    message: BlockMessage
    signature: str


class ModifiedOperator(OperatorKey):
    """TODO: Remove as soon as lido_sdk will support module_id"""
    module_id: int


class ModifiedOperatorKey(OperatorKey):
    """TODO: Remove as soon as lido_sdk will support module_id"""
    module_id: int


class MergedLidoValidator(TypedDict):
    validator: Validator
    key: ModifiedOperatorKey
