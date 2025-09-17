from dataclasses import dataclass, field
from functools import cached_property
from typing import Protocol

from eth_typing import BlockNumber
from hexbytes import HexBytes
from web3.types import Timestamp

from src.types import (
    BlockHash,
    BlockRoot,
    CommitteeIndex,
    EpochNumber,
    Gwei,
    SlotNumber,
    StateRoot,
    ValidatorIndex,
)
from src.utils.dataclass import FromResponse, Nested
from src.utils.types import hex_str_to_bytes


@dataclass
class BeaconSpecResponse(Nested, FromResponse):
    DEPOSIT_CHAIN_ID: int
    SLOTS_PER_EPOCH: int
    SECONDS_PER_SLOT: int
    DEPOSIT_CONTRACT_ADDRESS: str
    SLOTS_PER_HISTORICAL_ROOT: int


@dataclass
class GenesisResponse(Nested, FromResponse):
    genesis_time: int


@dataclass
class BlockRootResponse(FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot
    root: BlockRoot


@dataclass
class BlockHeaderMessage(Nested, FromResponse):
    slot: SlotNumber
    proposer_index: ValidatorIndex
    parent_root: BlockRoot
    state_root: StateRoot
    body_root: str


@dataclass
class BlockHeader(Nested, FromResponse):
    message: BlockHeaderMessage
    signature: str


@dataclass
class BlockHeaderResponseData(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
    root: BlockRoot
    canonical: bool
    header: BlockHeader


@dataclass
class BlockHeaderFullResponse(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
    execution_optimistic: bool
    data: BlockHeaderResponseData
    finalized: bool | None = None


@dataclass
class ExecutionPayload(Nested, FromResponse):
    parent_hash: BlockHash
    block_number: BlockNumber
    timestamp: Timestamp
    block_hash: BlockHash


@dataclass
class Checkpoint(Nested):
    epoch: EpochNumber
    root: BlockRoot


@dataclass
class AttestationData(Nested, FromResponse):
    slot: SlotNumber
    index: CommitteeIndex
    beacon_block_root: BlockRoot
    source: Checkpoint
    target: Checkpoint


@dataclass
class BlockAttestationResponse(Nested, FromResponse):
    aggregation_bits: str
    data: AttestationData
    committee_bits: str = ''


class BlockAttestation(Protocol):
    aggregation_bits: str
    committee_bits: str
    data: AttestationData


@dataclass
class SyncAggregate(FromResponse):
    sync_committee_bits: str


@dataclass
class BeaconBlockBody(Nested, FromResponse):
    execution_payload: ExecutionPayload
    attestations: list[BlockAttestationResponse]
    sync_aggregate: SyncAggregate


@dataclass
class BlockMessage(Nested, FromResponse):
    slot: SlotNumber
    proposer_index: ValidatorIndex
    parent_root: str
    state_root: StateRoot
    body: BeaconBlockBody


@dataclass
class ValidatorState(Nested, FromResponse):
    pubkey: str
    withdrawal_credentials: str
    effective_balance: Gwei
    slashed: bool
    activation_eligibility_epoch: EpochNumber
    activation_epoch: EpochNumber
    exit_epoch: EpochNumber
    withdrawable_epoch: EpochNumber


@dataclass
class Validator(Nested, FromResponse):
    index: ValidatorIndex
    balance: Gwei
    validator: ValidatorState

    @property
    def pubkey(self) -> HexBytes:
        return HexBytes(hex_str_to_bytes(self.validator.pubkey))


@dataclass
class BlockDetailsResponse(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: BlockMessage
    signature: str


@dataclass
class SlotAttestationCommittee(Nested, FromResponse):
    index: CommitteeIndex
    slot: SlotNumber
    validators: list[ValidatorIndex]


@dataclass
class PendingPartialWithdrawal(Nested):
    validator_index: ValidatorIndex
    amount: Gwei
    withdrawable_epoch: EpochNumber


@dataclass
class PendingDeposit(Nested):
    pubkey: str
    withdrawal_credentials: str
    amount: Gwei
    signature: str
    slot: SlotNumber


@dataclass
class BeaconStateView(Nested, FromResponse):
    """
    A view to BeaconState with only the required keys presented.
    @see https://github.com/ethereum/consensus-specs/blob/dev/specs/electra/beacon-chain.md#beaconstate
    """

    slot: SlotNumber
    validators: list[ValidatorState]
    balances: list[Gwei]
    slashings: list[Gwei]

    # These fields are new in Electra, so here are default values for backward compatibility.
    exit_balance_to_consume: Gwei = Gwei(0)
    earliest_exit_epoch: EpochNumber = EpochNumber(0)
    pending_deposits: list[PendingDeposit] = field(default_factory=list)
    pending_partial_withdrawals: list[PendingPartialWithdrawal] = field(default_factory=list)

    @cached_property
    def indexed_validators(self) -> list[Validator]:
        return [
            Validator(
                index=ValidatorIndex(i),
                balance=self.balances[i],
                validator=v,
            )
            for (i, v) in enumerate(self.validators)
        ]


@dataclass
class SyncCommittee(Nested, FromResponse):
    validators: list[ValidatorIndex]


@dataclass
class ProposerDuties(Nested, FromResponse):
    pubkey: str
    validator_index: ValidatorIndex
    slot: SlotNumber
