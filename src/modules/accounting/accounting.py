import logging
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache

from web3.types import Wei

from src.modules.accounting.typings import ReportData, ProcessingState
from src.modules.submodules.consensus import ConsensusModule, ZERO_HASH
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp, SlotNumber, Gwei
from src.utils.abi import named_tuple_to_dataclass
from src.web3py.extentions.lido_validators import LidoValidator, NodeOperatorIndex
from src.web3py.typings import Web3

logger = logging.getLogger(__name__)


class Accounting(BaseModule, ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

    def execute_module(self, blockstamp: BlockStamp):
        report_timestamp = self.get_blockstamp_for_report(blockstamp)
        if report_timestamp:
            self.process_report(*report_timestamp)

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> ProcessingState:
        return named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            ProcessingState,
        )

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.main_data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        extra_data_reported = processing_state.extra_data_items_count == processing_state.extra_data_items_submitted
        return not processing_state.main_data_submitted or not extra_data_reported

    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: BlockStamp, ref_slot: SlotNumber, with_finalization: bool = True) -> tuple:
        report_data = self._calculate_report(blockstamp, ref_slot, with_finalization)
        return report_data.as_tuple()

    def _calculate_report(self, blockstamp: BlockStamp, ref_slot: SlotNumber, with_finalization: bool = True) -> ReportData:
        validators_count, cl_balance = self._get_consensus_lido_state(blockstamp)

        finalization_share_rate = 0
        last_withdrawal_id_to_finalize = 0
        if with_finalization:
            finalization_share_rate = self._get_finalization_shares_rate(blockstamp)
            last_withdrawal_id_to_finalize = self._get_last_withdrawal_request_to_finalize(blockstamp)

        exit_validators_stats = defaultdict(int)
        exited_validators = self._get_exited_lido_validators(blockstamp, ref_slot)
        for (module_id, _), validators in exited_validators.items():
            exit_validators_stats[module_id] += len(validators)

        stacking_module_id_list, exit_validators_count = zip(*exit_validators_stats.items())

        report_data = ReportData(
            consensus_version=self.CONSENSUS_VERSION,
            ref_slot=ref_slot,
            validators_count=validators_count,
            cl_balance_gwei=cl_balance,
            stacking_module_id_with_exited_validators=stacking_module_id_list,
            count_exited_validators_by_stacking_module=exit_validators_count,
            withdrawal_vault_balance=self._get_withdrawal_balance(blockstamp),
            el_rewards_vault_balance=self._get_el_vault_balance(blockstamp),
            last_withdrawal_request_to_finalize=last_withdrawal_id_to_finalize,
            finalization_share_rate=finalization_share_rate,
            is_bunker=self._is_bunker(blockstamp),
            extra_data_format=0,  # TODO
            extra_data_hash=ZERO_HASH,  # TODO
            extra_data_items_count=0,  # TODO
        )

        return report_data

    def _get_consensus_lido_state(self, blockstamp: BlockStamp) -> tuple[int, Gwei]:
        lido_validators = self.w3.lido_validators.get_lido_validators(blockstamp)

        count = len(lido_validators)
        balance = Gwei(sum(int(validator.validator.balance) for validator in lido_validators))
        return count, balance

    def _get_exited_lido_validators(self, blockstamp: BlockStamp, ref_slot: SlotNumber) -> dict[NodeOperatorIndex, list[LidoValidator]]:
        lido_validators = deepcopy(self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp))

        def exit_filter(validator: LidoValidator) -> bool:
            return int(validator.validator.validator.exit_epoch) < ref_slot

        for index, validators in lido_validators.items():
            lido_validators[index] = list(filter(exit_filter, lido_validators[index]))

        return lido_validators

    def _get_withdrawal_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.w3.lido_contracts.withdrawal_vault.address,
            block_identifier=blockstamp.block_hash,
        ))

    def _get_el_vault_balance(self, blockstamp: BlockStamp) -> Wei:
        return Wei(self.w3.eth.get_balance(
            self.w3.lido_contracts.lido_execution_layer_rewards_vault.address,
            block_identifier=blockstamp.block_hash,
        ))

    def _get_last_withdrawal_request_to_finalize(self, blockstamp: BlockStamp) -> int:
        return 0

    def _get_finalization_shares_rate(self, blockstamp: BlockStamp) -> int:
        return 0

    def _is_bunker(self, blockstamp: BlockStamp) -> bool:
        return False

