from dataclasses import dataclass
from typing import Self, NewType

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
    shares_requested_to_burn: int
    withdrawal_finalization_batches: list[int]
    is_bunker: bool
    vaultsValues: list[int]
    vaultsNetCashFlows: list[int]
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
            self.vaultsValues,
            self.vaultsNetCashFlows,
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


@dataclass(frozen=True)
class LidoReportRebase:
    post_total_pooled_ether: int
    post_total_shares: int
    withdrawals: Wei
    el_reward: Wei


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
    cover_shares: int
    non_cover_shares: int


@dataclass
class WithdrawalRequestStatus:
    amount_of_st_eth: int
    amount_of_shares: int
    owner: ChecksumAddress
    timestamp: int
    is_finalized: bool
    is_claimed: bool


BunkerMode = NewType('BunkerMode', bool)
FinalizationShareRate = NewType('FinalizationShareRate', int)
ValidatorsCount = NewType('ValidatorsCount', int)
ValidatorsBalance = NewType('ValidatorsBalance', Gwei)

type SharesToBurn = int
type GenericExtraData = tuple[OperatorsValidatorCount, OperatorsValidatorCount, OracleReportLimits]
type RebaseReport = tuple[ValidatorsCount, ValidatorsBalance, WithdrawalVaultBalance, ELVaultBalance, SharesToBurn]
type WqReport = tuple[BunkerMode, FinalizationShareRate, FinalizationBatches]


@dataclass
class BeaconStat:
    deposited_validators: int
    beacon_validators: int
    beacon_balance: int
