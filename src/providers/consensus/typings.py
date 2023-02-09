from dataclasses import dataclass
from enum import Enum

from src.typings import StateRoot
from src.utils.dataclass import Nested


@dataclass
class BlockRootResponse:
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot
    root: StateRoot


@dataclass
class BlockMessage:
    slot: str
    proposer_index: str
    parent_root: str
    state_root: str
    body: dict


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


@dataclass
class ValidatorState:
    # All uint variables presents in str
    pubkey: str
    withdrawal_credentials: str
    effective_balance: str
    slashed: bool
    activation_eligibility_epoch: bool
    activation_epoch: str
    exit_epoch: str
    withdrawable_epoch: str


@dataclass
class Validator(Nested):
    index: int
    balance: int
    status: ValidatorStatus
    validator: ValidatorState


@dataclass
class BlockDetailsResponse(Nested):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: BlockMessage
    signature: str
