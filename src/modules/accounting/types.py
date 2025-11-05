import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from typing import NewType, Self

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from oz_merkle_tree import StandardMerkleTree
from web3.types import Wei

from src.constants import TOTAL_BASIS_POINTS
from src.providers.consensus.types import PendingDeposit, Validator
from src.types import (
    ELVaultBalance,
    FinalizationBatches,
    Gwei,
    OperatorsValidatorCount,
    SlotNumber,
    StakingModuleId,
    WithdrawalVaultBalance,
)
from src.utils.dataclass import FromResponse, Nested

BunkerMode = NewType('BunkerMode', bool)
ValidatorsCount = NewType('ValidatorsCount', int)
ValidatorsBalance = NewType('ValidatorsBalance', Gwei)

type Shares = NewType('Shares', int)
type VaultsTreeRoot = NewType('VaultsTreeRoot', bytes)
type VaultsTreeCid = NewType('VaultsTreeCid', str)
type VaultTreeNode = tuple[ChecksumAddress, Wei, int, int, int, int]

SECONDS_IN_YEAR = 365 * 24 * 60 * 60
BLOCKS_PER_YEAR = 2_628_000
FinalizationShareRate = NewType('FinalizationShareRate', int)


type SharesToBurn = int
type RebaseReport = tuple[ValidatorsCount, ValidatorsBalance, WithdrawalVaultBalance, ELVaultBalance, SharesToBurn]
type WqReport = tuple[BunkerMode, FinalizationBatches, FinalizationShareRate]


def snake_to_camel(s):
    parts = s.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])


@dataclass
class ReportData:
    consensus_version: int
    ref_slot: SlotNumber
    validators_count: int
    cl_balance_gwei: Gwei
    staking_module_ids_with_exited_validators: list[StakingModuleId]
    count_exited_validators_by_staking_module: list[int]
    withdrawal_vault_balance: Wei
    el_rewards_vault_balance: Wei
    shares_requested_to_burn: Shares
    withdrawal_finalization_batches: list[int]
    finalization_share_rate: int
    is_bunker: bool
    vaults_tree_root: VaultsTreeRoot
    vaults_tree_cid: VaultsTreeCid
    extra_data_format: int
    extra_data_hash: bytes
    extra_data_items_count: int

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensus_version,
            self.ref_slot,
            self.validators_count,
            self.cl_balance_gwei,
            self.staking_module_ids_with_exited_validators,
            self.count_exited_validators_by_staking_module,
            self.withdrawal_vault_balance,
            self.el_rewards_vault_balance,
            self.shares_requested_to_burn,
            self.withdrawal_finalization_batches,
            self.finalization_share_rate,
            self.is_bunker,
            self.vaults_tree_root,
            self.vaults_tree_cid,
            self.extra_data_format,
            self.extra_data_hash,
            self.extra_data_items_count,
        )


@dataclass
class AccountingProcessingState:
    current_frame_ref_slot: SlotNumber
    processing_deadline_time: SlotNumber
    main_data_hash: HexBytes
    main_data_submitted: bool
    extra_data_hash: HexBytes
    extra_data_format: int
    extra_data_submitted: bool
    extra_data_items_count: int
    extra_data_items_submitted: int


@dataclass
class OracleReportLimits:
    exited_validators_per_day_limit: int
    appeared_validators_per_day_limit: int
    annual_balance_increase_bp_limit: int
    simulated_share_rate_deviation_bp_limit: int
    max_validator_exit_requests_per_report: int
    max_items_per_extra_data_transaction: int
    max_node_operators_per_extra_data_item: int
    request_timestamp_margin: int
    max_positive_token_rebase: int
    initial_slashing_amount_p_wei: int | None = None
    inactivity_penalties_amount_p_wei: int | None = None
    cl_balance_oracles_error_upper_bp_limit: int | None = None

    @classmethod
    def from_response(cls, **kwargs) -> Self:
        # Compatability breaking rename. `churn_validators_per_day_limit` was split into:
        # exited_validators_per_day_limit and appeared_validators_per_day_limit
        # Unpack structure by order
        return cls(*kwargs.values())  # pylint: disable=no-value-for-parameter


type GenericExtraData = tuple[OperatorsValidatorCount, OracleReportLimits]


@dataclass
class BatchState:
    remaining_eth_budget: int
    finished: bool
    batches: list[int]
    batches_length: int

    def as_tuple(self):
        return (
            self.remaining_eth_budget,
            self.finished,
            self.batches,
            self.batches_length,
        )


@dataclass
class SharesRequestedToBurn:
    cover_shares: Shares
    non_cover_shares: Shares


@dataclass
class WithdrawalRequestStatus:
    amount_of_st_eth: int
    amount_of_shares: int
    owner: ChecksumAddress
    timestamp: int
    is_finalized: bool
    is_claimed: bool


@dataclass
class BeaconStat:
    deposited_validators: int
    beacon_validators: int
    beacon_balance: int


@dataclass(frozen=True)
class ReportSimulationPayload:
    timestamp: int
    time_elapsed: int
    cl_validators: int
    cl_balance: Wei
    withdrawal_vault_balance: Wei
    el_rewards_vault_balance: Wei
    shares_requested_to_burn: Shares
    withdrawal_finalization_batches: list[int]
    simulated_share_rate: int

    def as_tuple(self):
        return (
            self.timestamp,
            self.time_elapsed,
            self.cl_validators,
            self.cl_balance,
            self.withdrawal_vault_balance,
            self.el_rewards_vault_balance,
            self.shares_requested_to_burn,
            self.withdrawal_finalization_batches,
            self.simulated_share_rate,
        )


@dataclass(frozen=True)
class ReportSimulationFeeDistribution:
    module_fee_recipients: list[ChecksumAddress]
    module_ids: list[int]
    module_shares_to_mint: list[int]
    treasury_shares_to_mint: int


@dataclass(frozen=True)
class ReportSimulationResults:
    withdrawals_vault_transfer: Wei
    el_rewards_vault_transfer: Wei
    ether_to_finalize_wq: Wei
    shares_to_finalize_wq: Shares
    shares_to_burn_for_withdrawals: Shares
    total_shares_to_burn: SharesToBurn
    shares_to_mint_as_fees: Shares
    fee_distribution: ReportSimulationFeeDistribution
    principal_cl_balance: Wei
    pre_total_shares: Shares
    pre_total_pooled_ether: Wei
    post_internal_shares: Shares
    post_internal_ether: Wei
    post_total_shares: Shares
    post_total_pooled_ether: Wei


@dataclass
class OnChainIpfsVaultReportData(Nested, FromResponse):
    timestamp: int
    ref_slot: SlotNumber
    tree_root: VaultsTreeRoot
    report_cid: VaultsTreeCid


@dataclass
class VaultInfo(Nested, FromResponse):
    vault: ChecksumAddress
    aggregated_balance: Wei
    in_out_delta: Wei
    withdrawal_credentials: str
    liability_shares: Shares
    max_liability_shares: Shares
    mintable_st_eth: int
    share_limit: int
    reserve_ratio_bp: int
    forced_rebalance_threshold_bp: int
    infra_fee_bp: int
    liquidity_fee_bp: int
    reservation_fee_bp: int
    pending_disconnect: bool



@dataclass(frozen=True)
class VaultFee:
    infra_fee: int
    liquidity_fee: int
    reservation_fee: int
    prev_fee: int

    def total(self):
        return self.prev_fee + self.infra_fee + self.liquidity_fee + self.reservation_fee


VaultToValidators = dict[ChecksumAddress, list[Validator]]

VaultsMap = dict[ChecksumAddress, VaultInfo]
VaultTotalValueMap = dict[ChecksumAddress, Wei]

VaultFeeMap = dict[ChecksumAddress, VaultFee]
VaultReserveMap = dict[ChecksumAddress, int]
type VaultsReport = tuple[VaultsTreeRoot, VaultsTreeCid]
type VaultsData = tuple[list[VaultTreeNode], VaultsMap, VaultTotalValueMap]


class VaultTreeValueKey(Enum):
    VAULT_ADDRESS = "vaultAddress"
    TOTAL_VALUE = "totalValueWei"
    FEE = "fee"
    LIABILITY_SHARES = "liabilityShares"
    MAX_LIABILITY_SHARES = "maxLiabilityShares"
    SLASHING_RESERVE = "slashingReserve"


class VaultTreeValueIndex(Enum):
    VAULT_ADDRESS = 0
    TOTAL_VALUE_WEI = 1
    FEE = 2
    LIABILITY_SHARES = 3
    MAX_LIABILITY_SHARES = 4
    SLASHING_RESERVE = 5


@dataclass(frozen=True)
class MerkleValue:
    vault_address: ChecksumAddress
    total_value_wei: Wei
    fee: int
    liability_shares: int
    max_liability_shares: int
    slashing_reserve: int

    @staticmethod
    def leaf_index_to_data() -> dict[VaultTreeValueKey, VaultTreeValueIndex]:
        return {
            VaultTreeValueKey.VAULT_ADDRESS: VaultTreeValueIndex.VAULT_ADDRESS,
            VaultTreeValueKey.TOTAL_VALUE: VaultTreeValueIndex.TOTAL_VALUE_WEI,
            VaultTreeValueKey.FEE: VaultTreeValueIndex.FEE,
            VaultTreeValueKey.LIABILITY_SHARES: VaultTreeValueIndex.LIABILITY_SHARES,
            VaultTreeValueKey.MAX_LIABILITY_SHARES: VaultTreeValueIndex.MAX_LIABILITY_SHARES,
            VaultTreeValueKey.SLASHING_RESERVE: VaultTreeValueIndex.SLASHING_RESERVE,
        }

    @staticmethod
    def get_tree_value_ind(key: VaultTreeValueKey) -> int:
        return MerkleValue.leaf_index_to_data()[key].value


@dataclass(frozen=True)
class ExtraValue:
    in_out_delta: str
    prev_fee: str
    infra_fee: str
    liquidity_fee: str
    reservation_fee: str

    def to_camel_dict(self):
        orig = asdict(self)
        return {snake_to_camel(k): v for k, v in orig.items()}


@dataclass
class StakingVaultIpfsReport:
    format: str
    leaf_encoding: list[str]
    tree: list[str]
    values: list[MerkleValue]
    ref_slot: int
    block_number: int
    block_hash: str
    timestamp: int
    prev_tree_cid: str
    extra_values: dict[str, ExtraValue]

    @classmethod
    def parse_merkle_tree_data(cls, raw_bytes: bytes) -> "StakingVaultIpfsReport":
        data = json.loads(raw_bytes.decode("utf-8"))

        if data["format"] != StandardMerkleTree.FORMAT:
            raise ValueError("Invalid format of merkle tree")

        values: list[MerkleValue] = []
        vault_address_index = MerkleValue.get_tree_value_ind(VaultTreeValueKey.VAULT_ADDRESS)
        total_value_index = MerkleValue.get_tree_value_ind(VaultTreeValueKey.TOTAL_VALUE)
        fee_index = MerkleValue.get_tree_value_ind(VaultTreeValueKey.FEE)
        liability_shares_index = MerkleValue.get_tree_value_ind(VaultTreeValueKey.LIABILITY_SHARES)
        max_liability_shares_index = MerkleValue.get_tree_value_ind(VaultTreeValueKey.MAX_LIABILITY_SHARES)
        slashing_reserve_index = MerkleValue.get_tree_value_ind(VaultTreeValueKey.SLASHING_RESERVE)

        for entry in data["values"]:
            values.append(
                MerkleValue(
                    vault_address=entry["value"][vault_address_index],
                    total_value_wei=Wei(int(entry["value"][total_value_index])),
                    fee=int(entry["value"][fee_index]),
                    liability_shares=int(entry["value"][liability_shares_index]),
                    max_liability_shares=int(entry["value"][max_liability_shares_index]),
                slashing_reserve=int(entry["value"][slashing_reserve_index]),
            ))

        extra_values = {}
        for vault_addr, val in data.get("extraValues", {}).items():
            extra_values[vault_addr] = ExtraValue(
                in_out_delta=val["inOutDelta"],
                prev_fee=val["prevFee"],
                infra_fee=val["infraFee"],
                liquidity_fee=val["liquidityFee"],
                reservation_fee=val["reservationFee"],
            )

        return StakingVaultIpfsReport(
            format=data["format"],
            leaf_encoding=data["leafEncoding"],
            tree=data["tree"],
            values=values,
            ref_slot=data["refSlot"],
            block_hash=data["blockHash"],
            block_number=data["blockNumber"],
            timestamp=data["timestamp"],
            prev_tree_cid=data["prevTreeCID"],
            extra_values=extra_values,
        )


@dataclass(frozen=True)
class StakingFeeAggregateDistribution:
    modules_fee: int
    treasury_fee: int
    base_precision: int

    def lido_fee_bp(self):
        total_basis_points_dec = Decimal(TOTAL_BASIS_POINTS)
        numerator = Decimal(self.modules_fee + self.treasury_fee) * total_basis_points_dec
        denominator = Decimal(self.base_precision)

        lido_fee_bp = numerator / denominator
        if lido_fee_bp >= total_basis_points_dec:
            raise ValueError(f"Got incorrect lido_fee_bp: {lido_fee_bp} >= {total_basis_points_dec} bp")

        return lido_fee_bp


@dataclass(frozen=True)
class PendingBalances:
    pending_deposits: list[PendingDeposit]

    @property
    def total(self) -> Gwei:
        return Gwei(sum(deposit.amount for deposit in self.pending_deposits))

    @property
    def max(self) -> Gwei:
        return Gwei(max((deposit.amount for deposit in self.pending_deposits), default=0))

class ValidatorStage(Enum):
    NONE = 0
    PREDEPOSITED = 1
    PROVEN = 2
    ACTIVATED = 3
    COMPENSATED = 4


@dataclass(frozen=True)
class ValidatorStatus:
    stage: ValidatorStage
    staking_vault: ChecksumAddress
    node_operator: ChecksumAddress
