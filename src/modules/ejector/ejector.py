import logging
from functools import lru_cache

from web3.types import Wei

from src.constants import MAX_WITHDRAWALS_PER_PAYLOAD, FAR_FUTURE_EPOCH, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.modules.ejector.prediction import RewardsPredictionService
from src.modules.ejector.typings import ProcessingState
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.providers.consensus.typings import Validator
from src.typings import BlockStamp
from src.utils.abi import named_tuple_to_dataclass
from src.web3py.extentions.lido_validators import LidoValidator
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class Ejector(BaseModule, ConsensusModule):
    """
    1. Get withdrawals amount
    2. Get exit prediction
    Loop:
     a. Get validator
     b. Remove withdrawal amount
     c. Increase order
     d. Check new withdrawals epoches
     e. If withdrawals ok - exit
    3. Decode gotten lido validators
    4. Send hash + send data
    """
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    AVG_EXPECTING_TIME_IN_SWEEP_MULTIPLIER = 0.5

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.validators_exit_bus_oracle
        super().__init__(w3)

        self.prediction_service = RewardsPredictionService(w3)

    def execute_module(self, blockstamp: BlockStamp):
        self.process_report(blockstamp)
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.process_report(report_blockstamp)

    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: BlockStamp) -> tuple:
        # lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        #
        # ws = self.get_total_withdrawal_amount(blockstamp)

        validators = self.get_validators_to_eject(blockstamp)

        # pass validators to extra data

        return (
            self.CONSENSUS_VERSION,
            blockstamp.ref_slot,
            0,
            0,
            b'',
        )

    def get_validators_to_eject(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        chain_config = self._get_chain_config(blockstamp)

        to_withdraw_amount = self.get_total_unfinalized_withdrawal_requests_amount(blockstamp)
        rewards_speed = self.prediction_service.get_rewards_per_slot(blockstamp, chain_config)

        sweep = self._get_sweep_delay_in_slot(blockstamp)

        pass

    def get_total_unfinalized_withdrawal_requests_amount(self, blockstamp: BlockStamp) -> Wei:
        steth_to_finalize = self.w3.lido_contracts.withdrawal_queue_nft.functions.unfinalizedStETH().call(
            block_identifier=blockstamp.block_hash,
        )
        logger.info({'msg': 'Wei to finalize.'})
        return steth_to_finalize

    def _get_exit_epoch_for_next_validator(self, validators_to_eject_count: int):
        pass

    def _get_sweep_delay_in_slot(self, blockstamp: BlockStamp):
        validators = self.w3.cc.get_validators(blockstamp.state_root)

        def if_validators_balance_withdrawable(validator: Validator):
            if int(validator.validator.activation_epoch) > blockstamp.ref_epoch:
                return False

            if int(validator.balance) == 0:
                return False

            if validator.validator.withdrawal_credentials[:4] != ETH1_ADDRESS_WITHDRAWAL_PREFIX:
                return False

            return True

        validators_count = len(list(filter(if_validators_balance_withdrawable, validators)))
        return int(validators_count / MAX_WITHDRAWALS_PER_PAYLOAD * self.AVG_EXPECTING_TIME_IN_SWEEP_MULTIPLIER)

    # def get_val_to_eject(self):
    #     withdrawals_size = self.get_total_withdrawal_amount()
    #     max_vals = 150
    #     vals = []
    #
    #     budget = self.calculate_budget()
    #     if budget > withdrawals_size:
    #         return vals
    #
    #     for validator in range(self.exit_queue):
    #         vals.append(validator)
    #
    #         budget = self.calculate_budget(vals)
    #         if budget > withdrawals_size:
    #             return vals
    #
    # def calculate_budget(self):
    #     prediction = self.get_queue_size(len([1])) * self.get_prediction()
    #     ejection = self.get_ejecet_budget([])
    #     return prediction + ejection
    #
    # def get_queue_size(self, list_size):
    #     pass
    #
    # def get_prediction(self):
    #     pass
    #
    # def get_ejecet_budget(self):
    #     # Считаем бюджет валидатора
    #     pass

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> ProcessingState:
        return named_tuple_to_dataclass(
            self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash),
            ProcessingState,
        )

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state.data_submitted

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return self.is_main_data_submitted(blockstamp)
