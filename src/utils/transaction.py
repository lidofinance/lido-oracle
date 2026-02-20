import logging

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.exceptions import ContractLogicError
from web3.types import BlockData, TxParams, Wei

from src import constants, variables

logger = logging.getLogger(__name__)


def build_transaction_params(w3: Web3, transaction: ContractFunction, account: LocalAccount) -> TxParams:
    latest_block: BlockData = w3.eth.get_block("latest")
    max_priority_fee = Wei(
        min(
            variables.MAX_PRIORITY_FEE,
            max(
                w3.eth.fee_history(1, 'latest', [variables.PRIORITY_FEE_PERCENTILE])['reward'][0][0],
                variables.MIN_PRIORITY_FEE,
            )
        )
    )

    params: TxParams = {
        "from": account.address,
        "maxFeePerGas": Wei(
            latest_block["baseFeePerGas"] * 2 + max_priority_fee  # type: ignore[index]
        ),
        "maxPriorityFeePerGas": max_priority_fee,
        "nonce": w3.eth.get_transaction_count(account.address),
    }

    if gas := estimate_gas(transaction, account):
        params['gas'] = gas

    return params


def estimate_gas(transaction: ContractFunction, account: LocalAccount) -> int | None:
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


def sign_and_send_transaction(w3: Web3, transaction: ContractFunction, params: TxParams, account: LocalAccount) -> bytes:
    tx = transaction.build_transaction(params)
    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    return tx_hash
