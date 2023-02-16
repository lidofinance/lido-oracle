from dataclasses import dataclass

from hexbytes import HexBytes
from web3.types import Wei

from src.typings import SlotNumber, Gwei


@dataclass
class ReportData:
    consensus_version: int
    ref_slot: SlotNumber
    validators_count: int
    cl_balance_gwei: Gwei
    stacking_module_id_with_exited_validators: list[int]
    count_exited_validators_by_stacking_module: list[int]
    withdrawal_vault_balance: Wei
    el_rewards_vault_balance: Wei
    last_withdrawal_request_to_finalize: int
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
            self.stacking_module_id_with_exited_validators,
            self.count_exited_validators_by_stacking_module,
            self.withdrawal_vault_balance,
            self.el_rewards_vault_balance,
            self.last_withdrawal_request_to_finalize,
            self.finalization_share_rate,
            self.is_bunker,
            self.extra_data_format,
            self.extra_data_hash,
            self.extra_data_items_count,
        )


@dataclass
class ProcessingState:
    current_frame_ref_slot: SlotNumber
    processing_deadline_time: SlotNumber
    main_data_hash: HexBytes
    main_data_submitted: bool
    extra_data_hash: HexBytes
    extra_data_format: int
    extra_data_items_count: int
    extra_data_items_submitted: int
