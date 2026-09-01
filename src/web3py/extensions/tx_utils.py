import logging
from typing import TYPE_CHECKING

from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from web3.exceptions import ContractLogicError, TimeExhausted
from web3.module import Module
from web3.types import TxParams, TxReceipt

from src import variables
from src.metrics.prometheus.basic import TRANSACTIONS_COUNT, Status
from src.utils.input import prompt
from src.utils.transaction import build_transaction_params, sign_and_send_transaction


if TYPE_CHECKING:
    from src.web3py.types import Web3


logger = logging.getLogger(__name__)


class TransactionUtils(Module):
    w3: Web3

    def check_and_send_transaction(self, transaction) -> TxReceipt | None:
        if not self.w3.signer.active_signer:
            logger.info({'msg': 'No active signer available. Dry mode'})
            return None

        if self.w3.signer.is_delegated:
            transaction = self.w3.signer.wrap_call_for_delegation(transaction)

        params = build_transaction_params(self.w3, transaction, self.w3.signer.active_signer)

        if self._check_transaction(transaction, params):
            if not variables.DAEMON:
                return self._manual_tx_processing(transaction, params, self.w3.signer.active_signer)

            return self._send_transaction(transaction, params, self.w3.signer.active_signer)

        return None

    def _manual_tx_processing(self, transaction, params: TxParams, account: LocalAccount) -> TxReceipt | None:
        logger.warning({'msg': 'Send transaction in manual mode.'})
        msg = f'\nGoing to send transaction to blockchain: \nTx args:\n{transaction.args}\nTx params:\n{params}\n'
        if prompt(f'{msg}Should we send this TX? [y/n]: '):
            return self._send_transaction(transaction, params, account)
        return None

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

    def _send_transaction(
        self,
        transaction,
        params: TxParams,
        account: LocalAccount,
    ) -> TxReceipt | None:
        tx_hash = sign_and_send_transaction(self.w3, transaction, params, account)
        logger.info({"msg": "Transaction sent.", "value": tx_hash.hex()})

        return self._handle_sent_transaction(HexBytes(tx_hash))

    def _handle_sent_transaction(self, transaction_hash: HexBytes) -> TxReceipt | None:
        try:
            tx_receipt = self.w3.eth.wait_for_transaction_receipt(transaction_hash)
        except TimeExhausted:
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
