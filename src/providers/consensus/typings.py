from dataclasses import dataclass
from typing import Optional

from src.typings import BlockRoot, StateRoot
from src.utils.dataclass import Nested, FromResponse


@dataclass
class BlockRootResponse(FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot
    root: BlockRoot


@dataclass
class BlockHeaderMessage(FromResponse):
    slot: str
    parent_root: BlockRoot
    state_root: StateRoot


@dataclass
class BlockHeader(Nested, FromResponse):
    message: BlockHeaderMessage


@dataclass
class BlockHeaderResponseData(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
    root: BlockRoot
    canonical: bool
    header: BlockHeader


@dataclass
class BlockHeaderFullResponse(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
    data: BlockHeaderResponseData
    finalized: Optional[bool] = None


@dataclass
class ExecutionPayload(FromResponse):
    block_number: str
    block_hash: str
    timestamp: str


@dataclass
class BlockMessageBody(Nested, FromResponse):
    execution_payload: ExecutionPayload


@dataclass
class BlockMessage(Nested, FromResponse):
    slot: str
    parent_root: str
    state_root: StateRoot
    body: BlockMessageBody


@dataclass
class ValidatorState(FromResponse):
    # All uint variables presents in str
    pubkey: str
    withdrawal_credentials: str
    effective_balance: str
    slashed: bool
    activation_epoch: str
    exit_epoch: str
    withdrawable_epoch: str


@dataclass
class Validator(Nested, FromResponse):
    index: str
    balance: str
    validator: ValidatorState


@dataclass
class BlockDetailsResponse(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: BlockMessage
