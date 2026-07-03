from dataclasses import dataclass, field
from functools import cached_property
from typing import Protocol

from eth_typing import BlockNumber, HexStr
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
from src.utils.validator_state import get_max_effective_balance


@dataclass
class BeaconSpecResponse(Nested, FromResponse):
    DEPOSIT_CHAIN_ID: int
    SLOTS_PER_EPOCH: int
    DEPOSIT_CONTRACT_ADDRESS: str
    SLOTS_PER_HISTORICAL_ROOT: int
    SLOT_DURATION_MS: int = 0
    SECONDS_PER_SLOT: int = 0
    # EIP-7732 (Gloas): exact constant name to be confirmed against final spec
    GLOAS_FORK_EPOCH: EpochNumber = EpochNumber(2**64 - 1)

    class NeitherSlotDurationFieldPresent(Exception):
        pass

    class UnsupportedSlotDuration(Exception):
        pass

    class InconsistentSlotDuration(Exception):
        pass

    def __post_init__(self):
        """
        Consensus clients may provide either SECONDS_PER_SLOT (legacy) or SLOT_DURATION_MS
        (per consensus-specs#4926). This method ensures both fields are populated.

        Raises UnsupportedSlotDuration for fractional slot durations (e.g., 12500ms = 12.5s).
        While SLOT_DURATION_MS technically enables sub-second precision, fractional slot
        durations are extremely unlikely in practice - all networks use whole seconds.
        Oracle explicitly rejects them to prevent silent timing calculation errors.

        See: https://github.com/ethereum/consensus-specs/pull/4926
        """
        super().__post_init__()
        if self.SLOT_DURATION_MS == 0 and self.SECONDS_PER_SLOT == 0:
            raise BeaconSpecResponse.NeitherSlotDurationFieldPresent(
                "CL spec response contains neither SECONDS_PER_SLOT nor SLOT_DURATION_MS"
            )

        if self.SLOT_DURATION_MS != 0:
            if self.SLOT_DURATION_MS % 1000 != 0:
                raise BeaconSpecResponse.UnsupportedSlotDuration(
                    f"Non-integer slot duration not supported: {self.SLOT_DURATION_MS}ms "
                    f"({self.SLOT_DURATION_MS / 1000}s). Oracle requires whole-second slot durations."
                )

            if self.SECONDS_PER_SLOT != 0 and self.SLOT_DURATION_MS != self.SECONDS_PER_SLOT * 1000:
                raise BeaconSpecResponse.InconsistentSlotDuration(
                    f"Inconsistent slot duration fields: {self.SLOT_DURATION_MS=} "
                    f"does not match {self.SECONDS_PER_SLOT=}."
                )

        if self.SLOT_DURATION_MS == 0:
            self.SLOT_DURATION_MS = int(self.SECONDS_PER_SLOT * 1000)

        if self.SECONDS_PER_SLOT == 0:
            self.SECONDS_PER_SLOT = self.SLOT_DURATION_MS // 1000


@dataclass
class GenesisResponse(Nested, FromResponse):
    genesis_time: int
    genesis_validators_root: HexStr
    genesis_fork_version: HexStr


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

    def __post_init__(self):
        super().__post_init__()

        if self.effective_balance > get_max_effective_balance(self):
            raise ValueError(f"Validator {self} has invalid effective balance")


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
    pubkey: HexStr
    withdrawal_credentials: HexStr
    amount: Gwei
    signature: HexStr
    slot: SlotNumber

    def __post_init__(self):
        super().__post_init__()
        self.pubkey = HexStr(self.pubkey.lower())
        self.withdrawal_credentials = HexStr(self.withdrawal_credentials.lower())


@dataclass
class PendingConsolidation(Nested):
    source_index: int
    target_index: int


@dataclass
class ExpectedWithdrawal(Nested, FromResponse):
    """
    A single entry in BeaconState.payload_expected_withdrawals (EIP-7732).
    CL has already deducted these amounts from validator balances via process_withdrawals,
    but the matching EL credit has not yet arrived in the withdrawal vault.
    FromResponse ignores extra fields (index, address) from the API response.
    """

    validator_index: ValidatorIndex
    amount: Gwei


@dataclass
class BeaconStateView(Nested, FromResponse):
    """
    A view to BeaconState with only the required keys presented.
    @see https://github.com/ethereum/consensus-specs/blob/master/specs/electra/beacon-chain.md#beaconstate
    """

    slot: SlotNumber
    validators: list[ValidatorState]
    balances: list[Gwei]
    slashings: list[Gwei]
    exit_balance_to_consume: Gwei = Gwei(0)
    earliest_exit_epoch: EpochNumber = EpochNumber(0)
    pending_deposits: list[PendingDeposit] = field(default_factory=list)
    pending_partial_withdrawals: list[PendingPartialWithdrawal] = field(default_factory=list)
    pending_consolidations: list[PendingConsolidation] = field(default_factory=list)

    # These fields are new in Gloas (EIP-7732), default values for backward compatibility.
    payload_expected_withdrawals: list[ExpectedWithdrawal] = field(default_factory=list)

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
