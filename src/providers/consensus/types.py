from dataclasses import dataclass, field
from typing import Literal, Protocol

from src.constants import FAR_FUTURE_EPOCH
from src.types import BlockHash, BlockRoot, EpochNumber, Gwei, SlotNumber, StateRoot
from src.utils.dataclass import FromResponse, Nested


@dataclass
class BeaconSpecResponse(FromResponse):
    DEPOSIT_CHAIN_ID: str
    SLOTS_PER_EPOCH: str
    SECONDS_PER_SLOT: str
    DEPOSIT_CONTRACT_ADDRESS: str
    SLOTS_PER_HISTORICAL_ROOT: str
    ELECTRA_FORK_EPOCH: str = str(FAR_FUTURE_EPOCH)


@dataclass
class GenesisResponse(FromResponse):
    genesis_time: str
    genesis_validators_root: str
    genesis_fork_version: str


@dataclass
class BlockRootResponse(FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot
    root: BlockRoot


@dataclass
class BlockHeaderMessage(FromResponse):
    slot: str
    proposer_index: str
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
class ExecutionPayload(FromResponse):
    parent_hash: BlockHash
    block_number: str
    timestamp: str
    block_hash: BlockHash


@dataclass
class Checkpoint:
    epoch: str
    root: BlockRoot


@dataclass
class AttestationData(Nested, FromResponse):
    slot: str
    index: str | Literal["0"]
    beacon_block_root: BlockRoot
    source: Checkpoint
    target: Checkpoint


@dataclass
class BlockAttestationResponse(Nested, FromResponse):
    aggregation_bits: str
    data: AttestationData
    committee_bits: str | None = None


class BlockAttestationPhase0(Protocol):
    aggregation_bits: str
    data: AttestationData


class BlockAttestationEIP7549(BlockAttestationPhase0):
    committee_bits: str


type BlockAttestation = BlockAttestationPhase0 | BlockAttestationEIP7549


@dataclass
class BeaconBlockBody(Nested, FromResponse):
    execution_payload: ExecutionPayload
    attestations: list[BlockAttestation]


@dataclass
class BlockMessage(Nested, FromResponse):
    slot: str
    proposer_index: str
    parent_root: str
    state_root: StateRoot
    body: BeaconBlockBody


@dataclass
class ValidatorState(FromResponse):
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
class Validator(Nested, FromResponse):
    index: str
    balance: str
    validator: ValidatorState


@dataclass
class BlockDetailsResponse(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: BlockMessage
    signature: str


@dataclass
class SlotAttestationCommittee(FromResponse):
    index: str
    slot: str
    validators: list[str]


@dataclass
class PendingDeposit(Nested):
    pubkey: str
    withdrawal_credentials: str
    amount: Gwei
    signature: str
    slot: SlotNumber


@dataclass
class PendingPartialWithdrawal(Nested):
    validator_index: str
    amount: Gwei
    withdrawable_epoch: EpochNumber


@dataclass
class BeaconStateView(Nested, FromResponse):
    """A view to BeaconState with only the required keys presented"""

    slot: SlotNumber
    validators: list[ValidatorState]
    balances: list[Gwei]
    # This fields are new in Electra, so here are default values for backward compatibility.
    deposit_balance_to_consume: Gwei = Gwei(0)
    exit_balance_to_consume: Gwei = Gwei(0)
    earliest_exit_epoch: EpochNumber = EpochNumber(0)
    pending_deposits: list[PendingDeposit] = field(default_factory=list)
    pending_partial_withdrawals: list[PendingPartialWithdrawal] = field(default_factory=list)

    @property
    def indexed_validators(self) -> list[Validator]:
        return [
            Validator(
                index=str(i),
                balance=str(self.balances[i]),
                validator=v,
            )
            for (i, v) in enumerate(self.validators)
        ]
