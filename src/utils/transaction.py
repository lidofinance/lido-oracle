import logging

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.exceptions import ContractLogicError
from web3.types import BlockData, TxParams, Wei

from src import variables
from src.constants import EIP_7825_TX_GAS_LIMIT, EIP_8037_TX_MAX_TOTAL_GAS_LIMIT


logger = logging.getLogger(__name__)


class GasEstimateAboveCap(Exception):
    pass


def tx_gas_cap(is_glamsterdam: bool) -> int:
    fork_cap = EIP_8037_TX_MAX_TOTAL_GAS_LIMIT if is_glamsterdam else EIP_7825_TX_GAS_LIMIT
    if variables.TX_GAS_LIMIT is None:
        return fork_cap
    return min(fork_cap, variables.TX_GAS_LIMIT)


def build_transaction_params(
    w3: Web3,
    transaction: ContractFunction,
    account: LocalAccount,
    gas_cap: int,
) -> TxParams:
    latest_block: BlockData = w3.eth.get_block("latest")
    max_priority_fee = Wei(
        min(
            variables.MAX_PRIORITY_FEE,
            max(
                w3.eth.fee_history(1, 'latest', [variables.PRIORITY_FEE_PERCENTILE])['reward'][0][0],
                variables.MIN_PRIORITY_FEE,
            ),
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

    if gas := estimate_gas(transaction, account, gas_cap):
        params['gas'] = gas

    return params


def estimate_gas(transaction: ContractFunction, account: LocalAccount, gas_cap: int) -> int | None:
    """
    Returns None if the estimation reverts.
    Raises GasEstimateAboveCap if the estimate alone exceeds gas_cap: such a transaction can only run out of gas.
    """
    try:
        gas = transaction.estimate_gas({'from': account.address})
    except ContractLogicError as error:
        logger.warning({'msg': 'Can not estimate gas. Contract logic error.', 'error': str(error)})
        return None
    except ValueError as error:
        logger.warning({'msg': 'Can not estimate gas. Execution reverted.', 'error': str(error)})
        return None

    if gas > gas_cap:
        logger.error(
            {
                'msg': 'Estimated gas exceeds the transaction gas cap. Transaction is not sent.',
                'estimated_gas': gas,
                'gas_cap': gas_cap,
            }
        )
        raise GasEstimateAboveCap(f'Estimated gas {gas} exceeds the transaction gas cap {gas_cap}.')

    gas_with_addition = gas + variables.TX_GAS_ADDITION

    if gas_with_addition > gas_cap:
        logger.warning(
            {
                'msg': 'Gas addition is clamped to the transaction gas cap.',
                'estimated_gas': gas,
                'gas_addition': variables.TX_GAS_ADDITION,
                'gas_cap': gas_cap,
            }
        )
        return gas_cap

    return gas_with_addition


def sign_and_send_transaction(
    w3: Web3,
    transaction: ContractFunction,
    params: TxParams,
    account: LocalAccount,
) -> bytes:
    tx = transaction.build_transaction(params)
    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    return tx_hash
