from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.typings import BlockRoot, StateRoot
from src.utils.dataclass import Nested


@dataclass
class BlockRootResponse:
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot
    root: BlockRoot


@dataclass
class BlockHeaderMessage:
    slot: str
    proposer_index: str
    parent_root: str
    state_root: StateRoot
    body_root: str


@dataclass
class BlockHeader(Nested):
    message: BlockHeaderMessage
    signature: str


@dataclass
class BlockHeaderResponseData(Nested):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
    root: BlockRoot
    canonical: bool
    header: BlockHeader


@dataclass
class BlockHeaderFullResponse(Nested):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
    finalized: Optional[bool]
    execution_optimistic: bool
    data: BlockHeaderResponseData


@dataclass
class BlockMessage:
    slot: str
    proposer_index: str
    parent_root: str
    state_root: StateRoot
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
    activation_eligibility_epoch: str
    activation_epoch: str
    exit_epoch: str
    withdrawable_epoch: str


@dataclass
class Validator(Nested):
    index: str
    balance: str
    status: ValidatorStatus
    validator: ValidatorState


@dataclass
class BlockDetailsResponse(Nested):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: BlockMessage
    signature: str
