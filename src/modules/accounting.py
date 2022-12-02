import logging
import time
from collections import defaultdict
from typing import Tuple, Union, List

from hexbytes import HexBytes
from web3 import Web3
from web3.types import TxParams

from src.contracts import contracts
from src.modules.interface import OracleModule
from src.providers.beacon import BeaconChainClient
from src.providers.execution import check_transaction, sign_and_send_transaction
from src.providers.typings import ValidatorGroup, SlotNumber, MergedLidoValidator

from src.providers.validators import get_lido_validators, get_lido_node_operators
from src.variables import GAS_LIMIT, ACCOUNT

logger = logging.getLogger(__name__)


class Accounting(OracleModule):
    """Calculates total lido validators balance and reports it to execution layer"""

    def __init__(self, web3: Web3, beacon_chain_client: BeaconChainClient):
        logger.info({'msg': 'Initialize Oracle Accounting Module.'})

        self._w3 = web3
        self._beacon_chain_client = beacon_chain_client

        self._update_beacon_specs()

    def run_module(self, slot: SlotNumber, block_hash: HexBytes):
        """Check if epoch is reportable and try to send report if it is."""
        self._update_beacon_specs(block_identifier=block_hash)

        if self._is_epoch_reportable(block_hash):
            tx = self.build_report(slot, block_hash)

            if check_transaction(tx):
                if not self.is_current_member_in_current_frame_quorum(slot, block_hash):
                    logger.info({'msg': 'Not in current frame quorum. Sleep for 8 minutes.'})
                    time.sleep(60 * 8)

                sign_and_send_transaction(self._w3, tx, ACCOUNT)

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

    def _is_epoch_reportable(self, block_hash: HexBytes) -> bool:
        last_reported_epoch = self._get_last_reported_epoch(block_hash)
        logging.info({'msg': f'Get last reported epoch.', 'value': last_reported_epoch})

        last_reportable_epoch = self._get_latest_reportable_epoch(block_hash)
        logging.info({'msg': f'Get latest reportable epoch.', 'value': last_reportable_epoch})

        return last_reported_epoch < last_reportable_epoch

    def _get_last_reported_epoch(self, block_hash: HexBytes) -> int:
        block = self._w3.eth.getBlock(block_hash)

        from_block = int((block.timestamp - self.genesis_time) / self.seconds_per_slot)

        # One day step
        step = (self.epochs_per_frame + 1) * self.slots_per_epoch

        # Try to fetch and parse last 'Completed' event from the contract.
        for end in range(block.number, from_block, -step):
            start = max(end - step + 1, from_block)
            events = contracts.oracle.events.Completed.getLogs(fromBlock=start, toBlock=end)
            if events:
                event = events[-1]
                return event['args']['epochId']

        return 0

    def _get_latest_reportable_epoch(self, block_hash: HexBytes) -> int:
        finalized_epoch = int(self._beacon_chain_client.get_head_finality_checkpoints()['finalized']['epoch'])

        potentially_reportable_epoch = contracts.oracle.functions.getCurrentFrame().call(block_identifier=block_hash)[0]

        return min(
            potentially_reportable_epoch, (finalized_epoch // self.epochs_per_frame) * self.epochs_per_frame
        )

    # -----------------------------------------------------------------------
    def build_report(self, slot: SlotNumber, block_hash: HexBytes) -> TxParams:
        """
        function handleOracleReport(
            // CL values
            uint256 _beaconValidators,
            uint256 _beaconBalance,
            uint256[] calldata _stackingModuleId,
            uint256[] calldata _nodeOperatorsWithExitedValidators,
            uint256[] calldata _exitedValidatorsNumber,
            uint256 _totalExitedValidators,
            // EL values
            uint256 _wcBufferedEther,
            // decision
            uint256 _newDepositBufferWithdrawalsReserve,
            uint256[] calldata _requestIdToFinalizeUpTo,
            uint256[] calldata _finalizationSharesAmount,
            uint256[] calldata _finalizationPooledEtherAmount
        ) external;
        """
        beacon_validators_count, beacon_validators_balance = self._get_beacon_validators_stats(slot, block_hash)
        logger.info({
            'msg': 'Fetch lido validators.',
            'beacon_validators_count': beacon_validators_count,
            'beacon_validators_balance': beacon_validators_balance,
        })

        exited_validators = self._get_exited_validators(slot, block_hash)
        total_exited_validator = len(exited_validators)
        logger.info(
            {'msg': 'Get exited validators. Value is withdrawable validators count.', 'value': total_exited_validator})

        (
            stacking_module_ids,
            no_operators,
            exited_validators,
        ) = self._get_new_exited_validators(block_hash, exited_validators)
        logger.info({
            'msg': 'Fetch Lido exited validators.',
            'stacking_module_ids': stacking_module_ids,
            'no_operators': no_operators,
            'exited_validators': exited_validators,
        })

        wc_buffered_ether = self._get_wc_buffered_ether(block_hash)
        logger.info({'msg': 'Fetch wc buffered ETH.', 'value': wc_buffered_ether})

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

        pending_block = self._w3.eth.getBlock('pending')

        transaction = contracts.oracle.functions.reportBeacon(
            beacon_validators_count,
            beacon_validators_balance,
            stacking_module_ids,
            no_operators,
            exited_validators,
            total_exited_validator,
            wc_buffered_ether,
            last_requests_id_to_finalize,
            finalization_shares_amount,
            finalization_pooled_ether_amount,
        ).build_transaction({
            'from': ACCOUNT.address,
            'gas': GAS_LIMIT,
            'maxFeePerGas': pending_block.baseFeePerGas * 2 + self._w3.eth.max_priority_fee * 2,
            'maxPriorityFeePerGas': self._w3.eth.max_priority_fee * 2,
            "nonce": self._w3.eth.get_transaction_count(ACCOUNT.address),
        })

        return transaction

    def _get_beacon_validators_stats(self, slot: SlotNumber, block_hash: HexBytes) -> Tuple[int, int]:
        lido_validators = get_lido_validators(self._w3, block_hash, self._beacon_chain_client, slot)
        return len(lido_validators), sum(validator['validator']['balance'] for validator in lido_validators)

    def _get_exited_validators(self, slot: SlotNumber, block_hash: HexBytes) -> List[MergedLidoValidator]:
        lido_validators = get_lido_validators(self._w3, block_hash, self._beacon_chain_client, slot)
        return list(filter(lambda validator: validator['status'] in ValidatorGroup.WITHDRAWAL, lido_validators))

    def _get_new_exited_validators(
            self,
            block_hash: HexBytes,
            validators: List[MergedLidoValidator],
    ) -> Tuple[List[int], List[int], List[int]]:
        exited_validators = defaultdict(lambda: defaultdict(int))

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
                node_operator_id.append(operator['index'])

        return (
            stacking_module_id,
            node_operator_id,
            exited_validators_number,
        )

    def _get_wc_buffered_ether(self, block_hash: HexBytes) -> int:
        return self._w3.eth.get_balance(
            contracts.lido_execution_layer_rewards_vault.address,
            block_identifier=block_hash,
        )

    def _get_requests_finalization_report(self, block_hash: HexBytes) -> Tuple[List[int], List[int], List[int]]:
        last_finalized_request = contracts.withdrawal_queue.functions.finalizedQueueLength().call(block_identifier=block_hash)
        logger.info({'msg': 'Get last finalized request.', 'value': last_finalized_request})

        queue_len = contracts.withdrawal_queue.functions.queueLength().call(block_identifier=block_hash)
        logger.info({'msg': 'Get withdrawal queue len.', 'value': queue_len})

        prev_eth_amount = 0
        last_req_id = None

        last_requests_id_to_finalize = []
        finalization_shares_amount = []
        finalization_pooled_ether_amount = []

        for request_id in range(last_finalized_request + 1, queue_len):
            request = contracts.withdrawal_queue.functions.queue(request_id).call(block_identifier=block_hash)

            # req                                  req                      rep
            # [ ] [ fin slot ] ... [ prev report ] [ ] [ ] [ ] [ ] [ last finalize slot ] .... [ ]
            #                                                                             here
            pooled_eth = contracts.lido.functions.getTotalPooledEther().call(block_identifier=request.requestBlockNumber)
            shares_amount = contracts.lido.functions.getSharesByPooledEth(pooled_eth).call(block_identifier=request.requestBlockNumber)

            if prev_eth_amount != pooled_eth:
                if last_req_id is not None:
                    last_requests_id_to_finalize.append(last_req_id)

                finalization_shares_amount.append(shares_amount)
                finalization_pooled_ether_amount.append(pooled_eth)

            last_req_id = request_id

        last_requests_id_to_finalize.append(last_req_id)

        return last_requests_id_to_finalize, finalization_shares_amount, finalization_pooled_ether_amount

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

        report_no = slot / self.slots_per_epoch / self.epochs_per_frame

        # Oracles list that should report today
        quorum_today = [(report_no + x) % len(oracle_members) for x in range(quorum_size)]

        return oracle_holder_index in quorum_today
