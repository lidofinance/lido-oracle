import logging
from _typeshed import SupportsNext
from collections import defaultdict
from typing import List

from hexbytes import HexBytes
from web3 import Web3
from web3.types import TxParams

from src import variables
from src.contracts import contracts
from src.modules.interface import OracleModule
from src.providers.beacon import BeaconChainClient
from src.providers.execution import check_transaction, sign_and_send_transaction
from src.providers.typings import ValidatorGroup, Slot, Validator, MergedLidoValidator
from src.providers.validators import get_lido_validators
from src.variables import ACCOUNT

logger = logging.getLogger(__name__)


class Ejector(OracleModule):
    """
    Ejector (Optional Oracle Module)

    Decides how many validators should exit if we receive withdrawal requests.

    Logic:
    1. Checks how many ETH want to be withdrawn. (width_eth)
    2. Calculates ETH buffered on lido contract. (buff_eth)
    3. Calculates ETH on rewards contract. (reward_eth)
    4. Predicts rewards for one day. (predict_reward_eth)
    5. Get balance going to withdraw validators. (width_eth)
    7. Validators to withdraw - (width_eth - buff_eth - reward_eth - predict_reward_eth - width_eth) / 32 ETH

    All calculations done in wei.
    """

    def __init__(self, web3: Web3, beacon_client: BeaconChainClient):
        logger.info({'msg': 'Initialize Ejector module'})
        self._w3 = web3
        self._beacon_chain_client = beacon_client

    def run_module(self, slot: Slot, block_hash: HexBytes):
        """Get validators count to eject and create ejection event."""
        logger.info({'msg': 'Execute ejector.', 'block_hash': block_hash})
        wei_amount_to_eject = self.calc_wei_amount_to_eject(slot, block_hash)

        if wei_amount_to_eject > 0:
            logger.info({'msg': 'Start ejecting validators.'})
            self.eject_validators(wei_amount_to_eject, slot, block_hash)

    def calc_wei_amount_to_eject(self, slot: Slot, block_hash: HexBytes) -> int:
        """Calculate validators count to eject."""
        amount_wei_to_withdraw = self._get_withdrawal_requests_wei_amount(block_hash)
        logger.info({'msg': 'Calculate wei in withdrawal queue.', 'value': amount_wei_to_withdraw})

        buffered_eth = self._get_buffered_eth(block_hash)
        logger.info({'msg': 'Calculate wei in buffer.', 'value': buffered_eth})

        rewards_eth = self._get_rewards_eth(block_hash)
        logger.info({'msg': 'Calculate rewards.', 'value': rewards_eth})

        rewards_till_next_report = self._get_predicted_eth(block_hash, rewards_eth)
        logger.info({'msg': 'Predict rewards for next day.', 'value': rewards_till_next_report})

        exiting_validators_balances = self._get_exiting_validators_balances(slot, block_hash)
        logger.info({'msg': 'Get exiting validators balances.', 'value': exiting_validators_balances})

        result = amount_wei_to_withdraw - buffered_eth - rewards_eth - rewards_till_next_report - exiting_validators_balances
        logger.info({'msg': 'Wei to eject.', 'value': result})

        return result

    def _get_withdrawal_requests_wei_amount(self, block_hash: HexBytes) -> int:
        total_pooled_ether = contracts.pool.functions.getTotalPooledEther().call(block_identifier=block_hash)
        logger.info({'msg': 'Get total pooled ether.', 'value': total_pooled_ether})

        last_id_to_finalize = contracts.withdrawal_queue.functions.queueLength().call(block_identifier=block_hash)
        logger.info({'msg': 'Get last id to finalize.', 'value': total_pooled_ether})

        total_shares = contracts.lido.functions.getSharesByPooledEth().call(block_identifier=block_hash)
        logger.info({'msg': 'Get total shares.', 'value': total_shares})

        return contracts.withdrawal_queue.functions.calculateFinalizationParams(
            last_id_to_finalize,
            total_pooled_ether,
            total_shares,
        ).call(block_identifier=block_hash)

    def _get_buffered_eth(self, block_hash: HexBytes) -> int:
        return contracts.lido.functions.getBufferedEther().call(block_identifier=block_hash)

    def _get_rewards_eth(self, block_hash: HexBytes) -> int:
        return self._w3.eth.get_balance(
            contracts.lido_execution_layer_rewards_vault.address,
            block_identifier=block_hash,
        )

    def _get_predicted_eth(self, block_hash: HexBytes, current_eth: int) -> int:
        current_block = self._w3.eth.get_block(block_identifier=block_hash)

        blocks_in_day = int(24 * 60 * 60 / 12)

        previous_day_block_number = current_block['number'] - blocks_in_day

        previous_eth = self._w3.eth.get_balance(
            contracts.lido_execution_layer_rewards_vault.address,
            block_identifier=previous_day_block_number,
        )
        result = current_eth - previous_eth

        return result if result > 0 else 0

    def _get_exiting_validators_balances(self, slot: Slot, block_hash: HexBytes) -> int:
        validators = get_lido_validators(self._w3, block_hash, self._beacon_chain_client, slot)

        exiting_balance = 0

        for validator in validators:
            if validator['validator']['status'] in ValidatorGroup.GOING_TO_EXIT:
                exiting_balance += validator['validator']['balance']

        return exiting_balance

    def eject_validators(self, wei_amount: int, slot: Slot, block_hash: HexBytes):
        validators_to_eject = self._get_keys_to_eject(wei_amount, slot, block_hash)
        logger.info({'msg': f'Get list validators to eject. Validators count: {len(validators_to_eject)}'})

        if validators_to_eject:
            self._submit_keys_ejection(validators_to_eject)

    def _get_keys_to_eject(self, wei_amount_to_eject: int, slot: Slot, block_hash: HexBytes) -> List[Validator]:
        """Get NO operator's keys with bigger amount of keys"""
        validators = get_lido_validators(self._w3, block_hash, self._beacon_chain_client, slot)
        current_validators_wei_amount = 0
        validators_to_eject = []

        eject_validator_generator = self._get_validator_to_eject(validators)

        while current_validators_wei_amount < wei_amount_to_eject:
            validator = next(eject_validator_generator)

            current_validators_wei_amount += validator['balance']

            validators_to_eject.append(validator)

        return validators_to_eject

    def _get_validator_to_eject(self, lido_validators: List[MergedLidoValidator]) -> SupportsNext[Validator]:
        """
        Filter all exiting and exited validators.
        Sort them by index.
        Return by one validator from the node operator that have the largest amount of working validators.

        """
        validators = filter(lambda val: val['validator']['status'] not in ValidatorGroup.GOING_TO_EXIT, lido_validators)
        validators = sorted(validators, key=lambda val: val['validator']['index'])

        operators_validators = defaultdict(list)

        for validator in validators:
            operators_validators[(validator['key']['module_id'], validator['key']['operator_index'])].append(validator)

        while True:
            max_using_validators_by_no = 0
            operator_key = (0, 0)

            for key, validators in operators_validators.items():
                current_no_validator_count = len(validators)

                if current_no_validator_count > max_using_validators_by_no:
                    operator_key = key
                    max_using_validators_by_no = current_no_validator_count
                elif current_no_validator_count == max_using_validators_by_no:
                    if key[0] < operator_key[0]:
                        operator_key = key
                    elif key[1] < operator_key[1]:
                        operator_key = key

            yield operators_validators[operator_key].pop(0)

    def _prepare_transaction(self, validators_list: List[dict]) -> TxParams:
        modules_id = []
        node_operators_id = []
        validators_pub_keys = []

        for validator in validators_list:
            modules_id.append(validator['module_id'])
            node_operators_id.append(validator['operator_index'])
            validators_pub_keys.append(validator['key'])

        pending_block = self._w3.eth.get_block('pending')
        max_priority_fee = self._w3.eth.max_priority_fee * 2

        tx_params = {
            'from': variables.ACCOUNT.address,
            'gas': 1_000_000,
            'maxFeePerGas': pending_block.baseFeePerGas * 2 + max_priority_fee,
            'maxPriorityFeePerGas': max_priority_fee,
            "nonce": self._w3.eth.get_transaction_count(ACCOUNT.address),
        }

        ejection_report = contracts.validator_exit_bus.functions.reportKeysToEject(
            modules_id,
            node_operators_id,
            validators_pub_keys,
        ).build_transaction(tx_params)

        logger.info({
            'msg': 'Build ejection report.',
            'value': [modules_id, node_operators_id, validators_pub_keys],
        })
        logger.info({'msg': 'Transaction build.', 'value': tx_params})

        return ejection_report

    def _submit_keys_ejection(self, validators_list: List[dict]):
        logger.info({'msg': 'Start ejecting.', 'value': validators_list})

        ejection_report = self._prepare_transaction(validators_list)

        if check_transaction(ejection_report):
            sign_and_send_transaction(self._w3, ejection_report, ACCOUNT)
