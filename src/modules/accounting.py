import logging
import time
from collections import defaultdict
from typing import Tuple, Union, List

from hexbytes import HexBytes
from web3 import Web3
from web3.types import TxParams

from src.contracts import contracts
from src.metrics.prometheus.accounting import (
    ACCOUNTING_ACTIVE_VALIDATORS,
    ACCOUNTING_VALIDATORS_BALANCE,
    ACCOUNTING_EXITED_VALIDATORS,
    WC_BALANCE,
    LAST_FINALIZED_WITHDRAWAL_REQUEST,
    BUFFERED_ETHER_TO_RESERVE,
)
from src.modules.interface import OracleModule
from src.providers.beacon import BeaconChainClient
from src.web3_utils.tx_execution import check_transaction, sign_and_send_transaction

from src.web3_utils.contract_frame_utils import is_current_epoch_reportable, get_latest_reportable_epoch
from src.web3_utils.typings import SlotNumber, MergedLidoValidator

from src.web3_utils.validators import get_lido_validators, get_lido_node_operators
from src.variables import GAS_LIMIT, ACCOUNT


logger = logging.getLogger(__name__)


class Accounting(OracleModule):
    """Calculates total lido validators balance and reports it to execution layer"""

    def __init__(self, web3: Web3, beacon_chain_client: BeaconChainClient):
        logger.info({'msg': 'Initialize Oracle Accounting Module.'})

        self._w3 = web3
        self._beacon_chain_client = beacon_chain_client

        self._update_beacon_specs()

    def _update_beacon_specs(self, block_identifier: Union[str, HexBytes] = 'latest'):
        (
            self.epochs_per_frame,
            self.slots_per_epoch,
            self.seconds_per_slot,
            self.genesis_time,
        ) = contracts.oracle.functions.getBeaconSpec().call(block_identifier=block_identifier)
        logging.info({
            'msg': 'Update beacon specs.',
            'epochs_per_frame': self.epochs_per_frame,
            'slots_per_epoch': self.slots_per_epoch,
            'seconds_per_slot': self.seconds_per_slot,
            'genesis_time': self.genesis_time,
        })

    def run_module(self, slot: SlotNumber, block_hash: HexBytes):
        """Check if epoch is reportable and try to send report if it is."""
        self._update_beacon_specs(block_identifier=block_hash)

        if not is_current_epoch_reportable(self._w3, contracts.oracle, slot, block_hash):
            logger.info({'msg': 'Epoch is not reportable.'})
            return

        report_slot, report_block_hash = self._get_slot_and_block_hash_for_report(slot, block_hash)
        logger.info({'msg': f'Building report with slot: [{report_slot}] and block hash: [{report_block_hash}].'})

        tx = self.build_report(report_slot, report_block_hash)

        if not self.is_current_member_in_current_frame_quorum(report_slot, report_block_hash):
            logger.info({'msg': 'Not in current frame quorum. Sleep for 8 minutes.'})
            time.sleep(60 * 8)

        if check_transaction(tx, ACCOUNT.address):
            sign_and_send_transaction(self._w3, tx, ACCOUNT, GAS_LIMIT)

    def _get_slot_and_block_hash_for_report(self, slot: SlotNumber, block_hash: HexBytes) -> Tuple[SlotNumber, HexBytes]:
        reportable_epoch = get_latest_reportable_epoch(contracts.oracle, slot, block_hash)

        slot = self._beacon_chain_client.get_first_slot_in_epoch(reportable_epoch, self.slots_per_epoch)

        return SlotNumber(int(slot['message']['slot'])), slot['message']['body']['execution_payload']['block_hash']

    # -----------------------------------------------------------------------
    def build_report(self, slot: SlotNumber, block_hash: HexBytes) -> TxParams:
        """
        function handleCommitteeMemberReport(
            // Consensus info
            uint256 epochId;
            // CL values
            uint256 beaconValidators;
            uint64 beaconBalanceGwei;
            address[] stakingModules;
            uint256[] nodeOperatorsWithExitedValidators;
            uint64[] exitedValidatorsNumbers;
            // EL values
            uint256 wcBufferedEther;
            // decision
            uint256 newDepositBufferWithdrawalsReserve;
            uint256[] requestIdToFinalizeUpTo;
            uint256[] finalizationPooledEtherAmount;
            uint256[] finalizationSharesAmount;
        ) external;
        """
        beacon_validators_count, beacon_validators_balance = self._get_beacon_validators_stats(slot, block_hash)
        logger.info({
            'msg': 'Fetch lido validators.',
            'beacon_validators_count': beacon_validators_count,
            'beacon_validators_balance': beacon_validators_balance,
        })
        ACCOUNTING_ACTIVE_VALIDATORS.set(beacon_validators_count)
        ACCOUNTING_VALIDATORS_BALANCE.set(beacon_validators_balance)

        (
            stacking_module_ids,
            no_operators,
            exited_validators,
        ) = self._get_new_exited_validators(slot, block_hash)
        logger.info({
            'msg': 'Fetch Lido exited validators.',
            'stacking_module_ids': stacking_module_ids,
            'no_operators': no_operators,
            'exited_validators': exited_validators,
        })
        ACCOUNTING_EXITED_VALIDATORS.set(len(exited_validators))

        wc_buffered_ether = self._get_wc_buffered_ether(block_hash)
        logger.info({'msg': 'Fetch wc buffered ETH.', 'value': wc_buffered_ether})
        WC_BALANCE.set(wc_buffered_ether)

        buffered_ether_to_reserve = self._get_buffered_ether_to_reserve(block_hash)
        logger.info({'msg': 'Calculate buffered ether to reserve.', 'value': buffered_ether_to_reserve})
        BUFFERED_ETHER_TO_RESERVE.set(buffered_ether_to_reserve)

        (
            last_requests_id_to_finalize,
            finalization_shares_amount,
            finalization_pooled_ether_amount,
        ) = self._get_requests_finalization_report(block_hash)
        logger.info({
            'msg': 'Get withdrawals queue stats.',
            'last_requests_id_to_finalize': last_requests_id_to_finalize,
            'finalization_shares_amount': finalization_shares_amount,
            'finalization_pooled_ether_amount': finalization_pooled_ether_amount,
        })
        if last_requests_id_to_finalize:
            LAST_FINALIZED_WITHDRAWAL_REQUEST.set(last_requests_id_to_finalize[-1])

        transaction = contracts.oracle.functions.handleCommitteeMemberReport((
            int(slot / self.slots_per_epoch),
            beacon_validators_count,
            beacon_validators_balance,
            stacking_module_ids,
            no_operators,
            exited_validators,
            wc_buffered_ether,
            buffered_ether_to_reserve,
            last_requests_id_to_finalize,
            finalization_pooled_ether_amount,
            finalization_shares_amount,
        ))

        return transaction

    def _get_beacon_validators_stats(self, slot: SlotNumber, block_hash: HexBytes) -> Tuple[int, int]:
        # Should return balance in gwei!
        lido_validators = get_lido_validators(self._w3, block_hash, self._beacon_chain_client, slot)
        return len(lido_validators), sum(int(validator['validator']['balance']) for validator in lido_validators)

    def _get_exited_validators(self, slot: SlotNumber, block_hash: HexBytes) -> List[MergedLidoValidator]:
        lido_validators = get_lido_validators(self._w3, block_hash, self._beacon_chain_client, slot)

        withdrawable_validators = filter(lambda validator: int(validator['validator']['validator']['exit_epoch']) <= int(slot / self.slots_per_epoch), lido_validators)

        return list(withdrawable_validators)

    def _get_new_exited_validators(
            self,
            slot: SlotNumber,
            block_hash: HexBytes,
    ) -> Tuple[List[str], List[int], List[int]]:
        validators = self._get_exited_validators(slot, block_hash)

        exited_validators = defaultdict(int)

        for validator in validators:
            exited_validators[(validator['key']['module_id'], validator['key']['operator_index'])] += 1

        stacking_module_id = []
        node_operator_id = []
        exited_validators_number = []

        operators = get_lido_node_operators(self._w3, block_hash)
        for operator in operators:
            exited_validators_prev = operator['stoppedValidators']

            exited_validators_current = exited_validators[(operator['module_id'], operator['index'])]

            if exited_validators_prev != exited_validators_current:
                stacking_module_id.append(operator['module_id'])
                node_operator_id.append(operator['index'])
                exited_validators_number.append(exited_validators_current)

        return (
            stacking_module_id,
            node_operator_id,
            exited_validators_number,
        )

    def _get_wc_buffered_ether(self, block_hash: HexBytes) -> int:
        return self._w3.eth.get_balance(
            contracts.lido.functions.getELRewardsVault().call(block_identifier=block_hash),
            block_identifier=block_hash,
        )

    def _get_buffered_ether_to_reserve(self, block_hash: HexBytes) -> int:
        return 0

    def _get_requests_finalization_report(self, block_hash: HexBytes) -> Tuple[List[int], List[int], List[int]]:
        last_finalized_request = contracts.withdrawal_queue.functions.finalizedQueueLength().call(block_identifier=block_hash)
        logger.info({'msg': 'Get last finalized request.', 'value': last_finalized_request})

        queue_len = contracts.withdrawal_queue.functions.queueLength().call(block_identifier=block_hash)
        logger.info({'msg': 'Get withdrawal queue len.', 'value': queue_len})

        if queue_len == 0:
            logger.info({'msg': 'No requests in withdrawal queues.'})
            return [], [], []

        pooled_eth = contracts.lido.functions.getTotalPooledEther().call(block_identifier=block_hash)
        shares_amount = contracts.lido.functions.getSharesByPooledEth(pooled_eth).call(block_identifier=block_hash)

        return [queue_len - 1], [shares_amount], [pooled_eth]

    def is_current_member_in_current_frame_quorum(self, slot: SlotNumber, block_hash: HexBytes):
        """
        Shuffle oracle reports. It will be easier to check that oracle is ok.
        """
        if not ACCOUNT:
            return True

        quorum_size = contracts.oracle.functions.getQuorum().call(block_identifier=block_hash)
        oracle_members = contracts.oracle.functions.getOracleMembers().call(block_identifier=block_hash)

        try:
            oracle_holder_index = oracle_members.index(ACCOUNT.address)
        except ValueError:
            logger.warning('Account is not oracle member.')
            return True

        report_no = int(slot / self.slots_per_epoch / self.epochs_per_frame)

        # Oracles list that should report today
        quorum_today = [(report_no + x) % len(oracle_members) for x in range(quorum_size)]

        return oracle_holder_index in quorum_today
