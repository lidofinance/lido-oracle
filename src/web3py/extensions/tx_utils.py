import logging
from typing import Optional

from eth_account.signers.local import LocalAccount
from web3.contract.contract import ContractFunction
from web3.exceptions import ContractLogicError
from web3.module import Module
from web3.types import TxReceipt, Wei

from src.metrics.prometheus.basic import TRANSACTIONS_COUNT, Status, ACCOUNT_BALANCE

logger = logging.getLogger(__name__)


class TransactionUtils(Module):
    GAS_MULTIPLIER = 1.15

    def check_and_send_transaction(self, transaction, account: Optional[LocalAccount] = None) -> Optional[TxReceipt]:
        if not account:
            logger.info({'msg': 'No account provided to submit extra data. Dry mode'})
            return None

        ACCOUNT_BALANCE.labels(str(account.address)).set(self.w3.eth.get_balance(account.address))

        if self.check_transaction(transaction, account.address):
            return self.sign_and_send_transaction(transaction, account)

        return None

    @staticmethod
    def check_transaction(transaction, from_address: str) -> bool:
        """
        Returns:
        True - transaction succeed.
        False - transaction reverted.
        """
        logger.info({"msg": "Check transaction. Make static call.", "value": transaction.args})

        try:
            result = transaction.call({"from": from_address})
        except ContractLogicError as error:
            logger.warning({"msg": "Transaction reverted.", "error": str(error)})
            return False

        logger.info({"msg": "Transaction executed successfully.", "value": result})
        return True

    def sign_and_send_transaction(
        self,
        transaction: ContractFunction,
        account: Optional[LocalAccount] = None,
    ) -> Optional[TxReceipt]:
        if not account:
            logger.info({"msg": "No account provided. Dry mode."})
            return None

        pending_block = self.w3.eth.get_block("pending")

        tx = transaction.build_transaction(
            {
                "from": account.address,
                "gas": int(transaction.estimate_gas({'from': account.address}) * self.GAS_MULTIPLIER),
                "maxFeePerGas": Wei(
                    pending_block["baseFeePerGas"] * 2 + self.w3.eth.max_priority_fee
                ),
                "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
                "nonce": self.w3.eth.get_transaction_count(account.address),
            }
        )

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
