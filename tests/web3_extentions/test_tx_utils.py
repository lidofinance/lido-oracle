from unittest.mock import Mock

import pytest
from web3.exceptions import ContractLogicError

from src import variables
from src.constants import MAX_BLOCK_GAS_LIMIT
from src.modules.accounting.typings import Account
from src.utils import input


class Transaction:
    args = {}

    def estimate_gas(self, params: dict) -> int:
        return 0


@pytest.fixture
def tx():
    return Transaction()


@pytest.fixture
def account():
    return Account(
        address='0xF6d4bA61810778fF95BeA0B7DB2F103Dc042C5f7',
        _private_key='0x0',
    )


@pytest.mark.unit
def test_estimate_gas(web3, tx_utils, tx, account):
    tx.estimate_gas = Mock(return_value=MAX_BLOCK_GAS_LIMIT * 2)
    gas_amount = web3.transaction._estimate_gas(tx, account)
    assert gas_amount == MAX_BLOCK_GAS_LIMIT

    tx.estimate_gas = Mock(return_value=100)
    gas_amount = web3.transaction._estimate_gas(tx, account)
    assert gas_amount == 100 + variables.TX_GAS_ADDITION

    tx.estimate_gas = Mock(side_effect=ContractLogicError())
    gas_amount = web3.transaction._estimate_gas(tx, account)
    assert gas_amount is None


@pytest.mark.unit
def test_get_tx_params(web3, tx_utils, tx, account):
    gas_amount = 1000
    tx.estimate_gas = Mock(return_value=gas_amount)

    web3.eth.get_block = Mock(return_value={'baseFeePerGas': 20})
    web3.eth.fee_history = Mock(return_value={'reward': [[5]]})
    web3.eth.get_transaction_count = Mock(return_value=10)

    params = web3.transaction._get_transaction_params(tx, account)

    assert params['from'] == account.address
    assert params['maxFeePerGas'] == 20 * 2 + variables.MIN_PRIORITY_FEE
    assert params['maxPriorityFeePerGas'] == variables.MIN_PRIORITY_FEE
    assert params['nonce'] == 10
    assert params['gas'] == gas_amount + variables.TX_GAS_ADDITION

    tx.estimate_gas = Mock(side_effect=ContractLogicError())
    variables.MIN_PRIORITY_FEE = 1
    params = web3.transaction._get_transaction_params(tx, account)

    assert params['maxPriorityFeePerGas'] == 5
    assert 'from' in params
    assert 'maxFeePerGas' in params
    assert 'nonce' in params
    assert 'gas' not in params

    web3.eth.fee_history = Mock(return_value={'reward': [[1 * 10**18]]})
    params = web3.transaction._get_transaction_params(tx, account)

    assert params['maxPriorityFeePerGas'] == variables.MAX_PRIORITY_FEE


def test_manual_tx_processing(web3, tx_utils, tx, account):
    input.get_input = Mock(return_value='y')
    web3.transaction._sign_and_send_transaction = Mock()
    web3.transaction._manual_tx_processing(tx, {}, account)
    web3.transaction._sign_and_send_transaction.assert_called_once()


def test_manual_tx_processing_decline(web3, tx_utils, tx, account):
    input.get_input = Mock(return_value='n')
    web3.transaction._sign_and_send_transaction = Mock()
    web3.transaction._manual_tx_processing(tx, {}, account)
    web3.transaction._sign_and_send_transaction.assert_not_called()


def test_daemon_check_and_send_transaction(web3, tx_utils, tx, account, monkeypatch):
    input.get_input = Mock(return_value='n')
    with monkeypatch.context():
        monkeypatch.setattr(variables, "DAEMON", False)
        web3.transaction._sign_and_send_transaction = Mock()
        web3.transaction._get_transaction_params = Mock(return_value={})
        web3.transaction._check_transaction = Mock(return_value=True)
        web3.transaction.check_and_send_transaction(tx, account)
        web3.transaction._sign_and_send_transaction.assert_not_called()
