from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.typings import BlockRoot, StateRoot
from src.utils.dataclass import Nested, FromResponse, FromResponseCastedTypes


@dataclass
class BeaconSpecResponse(FromResponseCastedTypes):
    DEPOSIT_CHAIN_ID: int
    SLOTS_PER_EPOCH: int
    SECONDS_PER_SLOT: int
    DEPOSIT_CONTRACT_ADDRESS: str
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#time-parameters-1
    MIN_VALIDATOR_WITHDRAWABILITY_DELAY: int
    SHARD_COMMITTEE_PERIOD: int
    MAX_SEED_LOOKAHEAD: int
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#state-list-lengths
    EPOCHS_PER_SLASHINGS_VECTOR: int
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#rewards-and-penalties
    PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX: int
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#gwei-values
    EFFECTIVE_BALANCE_INCREMENT: int
    MAX_EFFECTIVE_BALANCE: int
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/capella/beacon-chain.md#execution
    MAX_WITHDRAWALS_PER_PAYLOAD: int
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#withdrawal-prefixes
    ETH1_ADDRESS_WITHDRAWAL_PREFIX: str
    # https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#validator-cycle
    MIN_PER_EPOCH_CHURN_LIMIT: int
    CHURN_LIMIT_QUOTIENT: int


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
    finalized: Optional[bool] = None


@dataclass
class BlockMessage(FromResponse):
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
    status: ValidatorStatus
    validator: ValidatorState


@dataclass
class BlockDetailsResponse(Nested, FromResponse):
    # https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2
    message: BlockMessage
    signature: str
