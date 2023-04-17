import logging
from typing import Optional

from eth_account.signers.local import LocalAccount
from web3.contract.contract import ContractFunction
from web3.exceptions import ContractLogicError
from web3.module import Module
from web3.types import TxReceipt, Wei, TxParams, BlockData

from src import variables, constants
from src.metrics.prometheus.basic import TRANSACTIONS_COUNT, Status
from src.utils.input import prompt

logger = logging.getLogger(__name__)


class TransactionUtils(Module):
    def check_and_send_transaction(self, transaction, account: Optional[LocalAccount] = None) -> Optional[TxReceipt]:
        if not account:
            logger.info({'msg': 'No account provided to submit extra data. Dry mode'})
            return None

        params = self._get_transaction_params(transaction, account)

        if self._check_transaction(transaction, params):
            if not variables.DAEMON:
                return self._manual_tx_processing(transaction, params, account)

            return self._sign_and_send_transaction(transaction, params, account)

        return None

    def _manual_tx_processing(self, transaction, params: TxParams, account: LocalAccount):
        logger.warning({'msg': 'Send transaction in manual mode.'})
        msg = (
            '\n'
            'Going to send transaction to blockchain: \n'
            f'Tx args:\n{transaction.args}\n'
            f'Tx params:\n{params}\n'
        )
        if prompt(f'{msg}Should we send this TX? [y/n]: '):
            self._sign_and_send_transaction(transaction, params, account)

    @staticmethod
    def _check_transaction(transaction, params: TxParams) -> bool:
        """
        Returns:
        True - transaction succeed.
        False - transaction reverted.
        """
        logger.info({"msg": "Check transaction. Make static call.", "value": transaction.args})

        try:
            result = transaction.call(params)
        except (ValueError, ContractLogicError) as error:
            logger.error({"msg": "Transaction reverted.", "error": str(error)})
            return False

        logger.info({"msg": "Transaction executed successfully.", "value": result})
        return True

    def _get_transaction_params(self, transaction: ContractFunction, account: LocalAccount):
        # get pending block doesn't work on erigon node in specific cases
        latest_block: BlockData = self.w3.eth.get_block("latest")
        max_priority_fee = Wei(
            min(
                variables.MAX_PRIORITY_FEE,
                max(
                    self.w3.eth.fee_history(1, 'latest', [variables.PRIORITY_FEE_PERCENTILE])['reward'][0][0],
                    variables.MIN_PRIORITY_FEE,
                )
            )
        )

        params: TxParams = {
            "from": account.address,
            "maxFeePerGas": Wei(
                latest_block["baseFeePerGas"] * 2 + max_priority_fee
            ),
            "maxPriorityFeePerGas": max_priority_fee,
            "nonce": self.w3.eth.get_transaction_count(account.address),
        }

        if gas := self._estimate_gas(transaction, account):
            params['gas'] = gas

        return params

    @staticmethod
    def _estimate_gas(transaction: ContractFunction, account: LocalAccount) -> Optional[int]:
        """If transaction throws exception return None"""
        try:
            gas = transaction.estimate_gas({'from': account.address})
        except ContractLogicError as error:
            logger.warning({'msg': 'Can not estimate gas. Contract logic error.', 'error': str(error)})
            return None
        except ValueError as error:
            logger.warning({'msg': 'Can not estimate gas. Execution reverted.', 'error': str(error)})
            return None

        return min(
            constants.MAX_BLOCK_GAS_LIMIT,
            gas + variables.TX_GAS_ADDITION,
        )

    def _sign_and_send_transaction(
        self,
        transaction: ContractFunction,
        params: Optional[TxParams],
        account: LocalAccount,
    ) -> Optional[TxReceipt]:
        tx = transaction.build_transaction(params)
        signed_tx = self.w3.eth.account.sign_transaction(tx, account.key)

        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        logger.info({"msg": "Transaction sent.", "value": tx_hash.hex()})

        tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

        if not tx_receipt:
            TRANSACTIONS_COUNT.labels(status=Status.FAILURE).inc()
            logger.warning({"msg": "Transaction was not found in blockchain after 120 seconds."})
            return None

        logger.info(
            {
                "msg": "Transaction is in blockchain.",
                "blockHash": tx_receipt["blockHash"].hex(),
                "blockNumber": tx_receipt["blockNumber"],
                "gasUsed": tx_receipt["gasUsed"],
                "effectiveGasPrice": tx_receipt["effectiveGasPrice"],
                "status": tx_receipt["status"],
                "transactionHash": tx_receipt["transactionHash"].hex(),
                "transactionIndex": tx_receipt["transactionIndex"],
            }
        )

        if tx_receipt["status"] == 1:
            TRANSACTIONS_COUNT.labels(status=Status.SUCCESS).inc()
        else:
            TRANSACTIONS_COUNT.labels(status=Status.FAILURE).inc()

        return tx_receipt
