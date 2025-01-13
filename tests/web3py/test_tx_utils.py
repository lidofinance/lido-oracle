import unittest
from collections import defaultdict
from unittest.mock import Mock, MagicMock, patch

import pytest
from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from web3.exceptions import ContractLogicError, TimeExhausted

from src import variables
from src.constants import MAX_BLOCK_GAS_LIMIT
from src.utils import input
from src.web3py.contract_tweak import ContractFunction
from src.web3py.extensions import TransactionUtils
from tests.conftest import Account


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

    web3.eth.fee_history = Mock(return_value={'reward': [[1 * 10 ** 18]]})
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


def test_find_transaction_timeout(web3, tx_utils, tx, account, monkeypatch):
    web3.eth.wait_for_transaction_receipt = Mock(side_effect=TimeExhausted())

    assert not web3.transaction._handle_sent_transaction('0x000001')

    web3.eth.wait_for_transaction_receipt = Mock(
        return_value={
            'blockHash': b'',
            'blockNumber': '',
            'gasUsed': '',
            'effectiveGasPrice': '',
            'status': '',
            'transactionHash': b'',
            'transactionIndex': '',
        }
    )

    assert web3.transaction._handle_sent_transaction('0x000001')


class TestTransactionUtils(unittest.TestCase):

    def setUp(self):
        w3 = MagicMock()
        self.utils = TransactionUtils(w3)

    def test_check_and_send_transaction_dry_mode(self):
        transaction = MagicMock()
        result = self.utils.check_and_send_transaction(transaction)

        self.assertIsNone(result)

    @patch('src.web3py.extensions.prompt', return_value=True)
    @patch('src.web3py.extensions.TransactionUtils._sign_and_send_transaction')
    def test_manual_transaction_processing(self, mock_sign_send, mock_prompt):
        transaction = MagicMock()
        params = {'from': '0x123'}
        account = MagicMock(spec=LocalAccount)

        self.utils._manual_tx_processing(transaction, params, account)

        mock_prompt.assert_called()
        mock_sign_send.assert_called_with(transaction, params, account)

    def test_check_transaction_reverted(self):
        transaction = MagicMock()
        transaction.call.side_effect = ValueError("Reverted")
        params = {'from': '0x123'}

        result = self.utils._check_transaction(transaction, params)

        self.assertFalse(result)

    @patch('src.web3py.extensions.TransactionUtils._estimate_gas', return_value=None)
    def test_get_transaction_params_without_gas(self, mock_estimate_gas, monkeypatch):
        account = MagicMock(spec=LocalAccount)
        account.address = "0x123"
        transaction = MagicMock(spec=ContractFunction)

        latest_block = {'baseFeePerGas': 10}
        self.utils.w3.eth.get_block.return_value = latest_block
        self.utils.w3.eth.get_transaction_count.return_value = 1
        self.utils.w3.eth.fee_history.return_value = {'reward': [[5]]}

        with monkeypatch.context():
            monkeypatch.setattr(variables, "MAX_PRIORITY_FEE", 20)
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 2)
            monkeypatch.setattr(variables, "PRIORITY_FEE_PERCENTILE", 10)
            params = self.utils._get_transaction_params(transaction, account)

            self.assertNotIn('gas', params)
            self.assertEqual(params['nonce'], 1)

    def test_estimate_gas_failure(self):
        transaction = MagicMock()
        transaction.estimate_gas.side_effect = ValueError("Execution reverted")
        account = MagicMock(spec=LocalAccount)
        account.address = "0x123"

        gas = self.utils._estimate_gas(transaction, account)

        self.assertIsNone(gas)

    @patch('src.web3py.extensions.TransactionUtils._handle_sent_transaction')
    def test_sign_and_send_transaction(self, mock_handle_sent):
        transaction = MagicMock()
        params = {'from': '0x123'}
        account = MagicMock(spec=LocalAccount)
        account.key = "dummy_key"

        built_tx = {'key': 'value'}
        transaction.build_transaction.return_value = built_tx

        signed_tx = MagicMock()
        signed_tx.rawTransaction = HexBytes("0xabc")
        self.utils.w3.eth.account.sign_transaction.return_value = signed_tx

        tx_hash = HexBytes("0x123")
        self.utils.w3.eth.send_raw_transaction.return_value = tx_hash

        self.utils._sign_and_send_transaction(transaction, params, account)

        self.utils.w3.eth.send_raw_transaction.assert_called_with(signed_tx.rawTransaction)
        mock_handle_sent.assert_called_with(tx_hash)
