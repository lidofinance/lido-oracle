import logging
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.types import TxParams


logger = logging.getLogger(__name__)


def check_transaction(transaction: TxParams) -> bool:
    """
        Returns:
        True - transaction succeed.
        False - transaction reverted.
    """
    logger.info({'msg': 'Check transaction locally.', 'value': transaction})

    try:
        result = transaction.call()
    except ContractLogicError as error:
        logger.warning({'msg': 'Transaction reverted.', 'error': str(error)})
        return False

    logger.info({'msg': 'Transaction executed successfully.', 'value': result})
    return True


def sign_and_send_transaction(w3: Web3, transaction: TxParams, account: Optional[Account] = None):
    if not account:
        logger.info({'msg': 'No account provided. Draft mode.'})
        return

    signed_tx = w3.eth.account.sign_transaction(transaction, account.privateKeyToAccount)
    # signed_tx = w3.eth.account.sign_transaction(transaction, account.privateKey)

    tx_hash = w3.eth.sendRawTransaction(signed_tx.rawTransaction)
    logger.info({'msg': 'Transaction sent.', 'value': tx_hash})

    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    logger.info({'msg': 'Transaction validated.', 'value': tx_receipt})

    return tx_receipt