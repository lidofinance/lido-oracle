from dataclasses import dataclass

from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3.types import Wei

from src.typings import SlotNumber, Gwei
from src.web3py.extensions.lido_validators import StakingModuleId


@dataclass
class ReportData:
    consensus_version: int
    ref_slot: SlotNumber
    validators_count: int
    cl_balance_gwei: Gwei
    staking_module_id_with_exited_validators: list[StakingModuleId]
    count_exited_validators_by_staking_module: list[int]
    withdrawal_vault_balance: Wei
    el_rewards_vault_balance: Wei
    shares_requested_to_burn: int
    withdrawal_finalization_batches: list[int]
    finalization_share_rate: int
    is_bunker: bool
    extra_data_format: int
    extra_data_hash: HexBytes
    extra_data_items_count: int

    def as_tuple(self):
        # Tuple with report in correct order
        return (
            self.consensus_version,
            self.ref_slot,
            self.validators_count,
            self.cl_balance_gwei,
            self.staking_module_id_with_exited_validators,
            self.count_exited_validators_by_staking_module,
            self.withdrawal_vault_balance,
            self.el_rewards_vault_balance,
            self.shares_requested_to_burn,
            self.withdrawal_finalization_batches,
            self.finalization_share_rate,
            self.is_bunker,
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
    churn_validators_per_day_limit: int
    one_off_cl_balance_decrease_bp_limit: int
    annual_balance_increase_bp_limit: int
    simulated_share_rate_deviation_bp_limit: int
    max_validator_exit_requests_per_report: int
    max_accounting_extra_data_list_items_count: int
    max_node_operators_per_extra_data_item_count: int
    request_timestamp_margin: int
    max_positive_token_rebase: int


@dataclass(frozen=True)
class LidoReportRebase:
    post_total_pooled_ether: int
    post_total_shares: int
    withdrawals: Wei
    el_reward: Wei


@dataclass
class Account:
    address: ChecksumAddress
    _private_key: HexBytes


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
            self.batches_length
        )


@dataclass
class SharesRequestedToBurn:
    cover_shares: int
    non_cover_shares: int
