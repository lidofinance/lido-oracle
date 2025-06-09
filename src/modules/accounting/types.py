from dataclasses import dataclass
from typing import Self, NewType, List

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.types import Wei

from src.types import (
    SlotNumber,
    Gwei,
    StakingModuleId,
    FinalizationBatches,
    ELVaultBalance,
    WithdrawalVaultBalance,
    OperatorsValidatorCount,
)

BunkerMode = NewType('BunkerMode', bool)
ValidatorsCount = NewType('ValidatorsCount', int)
ValidatorsBalance = NewType('ValidatorsBalance', Gwei)

type Shares = NewType('Shares', int)
type VaultsTreeRoot = NewType('VaultsTreeRoot', bytes)
type VaultsTreeCid = NewType('VaultsTreeCid', str)
type VaultTreeNode = tuple[str, int, int, int, int]

SECONDS_IN_YEAR = 365 * 24 * 60 * 60
BLOCKS_PER_YEAR = 2_628_000

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
    is_bunker: bool
    vaults_total_treasury_fees_shares: Shares
    vaults_total_deficit: int
    tree_root: VaultsTreeRoot
    tree_cid: VaultsTreeCid
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
            self.is_bunker,
            self.vaults_total_treasury_fees_shares,
            self.vaults_total_deficit,
            self.tree_root,
            self.tree_cid,
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


@dataclass
class BatchState:
    remaining_eth_budget: int
    finished: bool
    batches: tuple[int, ...]
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


type SharesToBurn = Shares
type GenericExtraData = tuple[OperatorsValidatorCount, OperatorsValidatorCount, OracleReportLimits]
type RebaseReport = tuple[ValidatorsCount, ValidatorsBalance, WithdrawalVaultBalance, ELVaultBalance, SharesToBurn]
type WqReport = tuple[BunkerMode, FinalizationBatches]


@dataclass
class BeaconStat:
    deposited_validators: int
    beacon_validators: int
    beacon_balance: int


@dataclass(frozen=True)
class ReportValues:
    timestamp: int
    time_elapsed: int
    cl_validators: int
    cl_balance: Wei
    withdrawal_vault_balance: Wei
    el_rewards_vault_balance: Wei
    shares_requested_to_burn: Shares
    withdrawal_finalization_batches: List[int]
    vaults_total_deficit: int


@dataclass(frozen=True)
class StakingRewardsDistribution:
    recipients: List[ChecksumAddress]
    module_ids: List[int]
    modules_fees: List[int]
    total_fee: int
    precision_points: int


@dataclass(frozen=True)
class ReportResults:
    withdrawals: Wei
    el_rewards: Wei
    ether_to_finalize_wq: Wei
    shares_to_finalize_wq: Shares
    shares_to_burn_for_withdrawals: Shares
    total_shares_to_burn: SharesToBurn
    shares_to_mint_as_fees: Shares
    reward_distribution: StakingRewardsDistribution
    principal_cl_balance: Wei
    post_internal_shares: Shares
    post_internal_ether: Wei
    pre_total_shares: Shares
    pre_total_pooled_ether: Wei
    post_total_shares: Shares
    post_total_pooled_ether: Wei


@dataclass(frozen=True)
class VaultSocket:
    vault: ChecksumAddress
    share_limit: Shares
    liability_shares: Shares
    reserve_ratio_bp: int
    rebalance_threshold_bp: int
    treasury_fee_bp: int
    pending_disconnect: bool


@dataclass
class VaultData:
    vault_ind: int
    balance_wei: Wei
    in_out_delta: Wei
    liability_shares: Shares
    fee: int
    address: ChecksumAddress
    withdrawal_credentials: str
    # Feature smart contract release
    share_limit: int
    minted_StETH: int
    mintable_capacity_StETH: int
    reserve_ratioBP: int
    forced_rebalance_thresholdBP: int
    infra_feeBP: int
    liquidity_feeBP: int
    reservation_feeBP: int
    pending_disconnect: bool


@dataclass
class LatestReportData:
    timestamp: int
    tree_root: VaultsTreeRoot
    cid: VaultsTreeCid

@dataclass
class VaultInfoRaw:
    vault: ChecksumAddress
    balance: Wei
    in_out_delta: Wei
    withdrawal_credentials: str
    liability_shares: Shares
    # Feature smart contract release
    share_limit: int
    reserve_ratioBP: int
    forced_rebalance_thresholdBP: int
    infra_feeBP: int
    liquidity_feeBP: int
    reservation_feeBP: int
    pending_disconnect: bool
    mintable_capacity_StETH: int
    vault_ind: int

@dataclass
class VaultInfo(VaultInfoRaw):
    vault_ind: int

VaultsMap = dict[ChecksumAddress, VaultInfo]
VaultTotalValue = int
VaultsTotalValues = list[VaultTotalValue]
type VaultsReport = tuple[VaultsTreeRoot, VaultsTreeCid]
type VaultsData = tuple[list[VaultTreeNode], VaultsMap, VaultsTotalValues]


@dataclass
class MerkleValue:
    vault_address: str
    total_value_wei: int
    in_out_delta: int
    fee: int
    liability_shares: int

@dataclass
class MerkleTreeData:
    format: str
    leaf_encoding: List[str]
    tree: List[str]
    values: List[MerkleValue]
    tree_indices: List[int]
    merkle_tree_root: str
    ref_slot: int
    block_number: int
    timestamp: int
    proofs_cid: str
    prev_tree_cid: str
