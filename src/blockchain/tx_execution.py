import logging
from typing import Optional

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.types import TxParams

from src.metrics.prometheus.basic import TX_SEND, TX_FAILURE

logger = logging.getLogger(__name__)


def check_transaction(transaction, from_address: str) -> bool:
    """
    Returns:
    True - transaction succeed.
    False - transaction reverted.
    """
    logger.info({"msg": "Check transaction locally.", "value": transaction.args})

    try:
        result = transaction.call({"from": from_address})
    except ContractLogicError as error:
        logger.warning({"msg": "Transaction reverted.", "error": str(error)})
        return False

    logger.info({"msg": "Transaction executed successfully.", "value": result})
    return True


def sign_and_send_transaction(
    w3: Web3,
    transaction: TxParams,
    account: Optional[LocalAccount] = None,
    gas_limit: int = 2000000,
):
    if not account:
        logger.info({"msg": "No account provided. Draft mode."})
        return

    pending_block = w3.eth.get_block("pending")

    tx = transaction.build_transaction(
        {
            "from": account.address,
            "gas": gas_limit,
            "maxFeePerGas": pending_block.baseFeePerGas * 2 + w3.eth.max_priority_fee,
            "maxPriorityFeePerGas": w3.eth.max_priority_fee,
            "nonce": w3.eth.get_transaction_count(account.address),
        }
    )

    signed_tx = w3.eth.account.sign_transaction(tx, account._private_key)

    tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    TX_SEND.inc()
    logger.info({"msg": "Transaction sent.", "value": tx_hash.hex()})

    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info(
        {
            "msg": "Transaction in blockchain.",
            "blockHash": tx_receipt.blockHash.hex(),
            "blockNumber": tx_receipt.blockNumber,
            "gasUsed": tx_receipt.gasUsed,
            "effectiveGasPrice": tx_receipt.effectiveGasPrice,
            "status": tx_receipt.status,
            "transactionHash": tx_receipt.transactionHash.hex(),
            "transactionIndex": tx_receipt.transactionIndex,
        }
    )

    if tx_receipt.status != 122:
        TX_FAILURE.inc()
