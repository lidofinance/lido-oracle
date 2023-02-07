from enum import Enum
from typing import TypedDict

from src.typings import StateRoot


class BlockRootResponse(TypedDict):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot
    root: StateRoot


class BlockDetailsResponse(TypedDict):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: 'BlockMessage'
    signature: str


class BlockMessage(TypedDict):
    slot: str
    proposer_index: str
    parent_root: str
    state_root: str
    body: dict


class Validator(TypedDict):
    index: int
    balance: int
    status: 'ValidatorStatus'
    validator: 'ValidatorState'


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


class ValidatorState(TypedDict):
    # All uint variables presents in str
    pubkey: str
    withdrawal_credentials: str
    effective_balance: str
    slashed: bool
    activation_eligibility_epoch: bool
    activation_epoch: str
    exit_epoch: str
    withdrawable_epoch: str
