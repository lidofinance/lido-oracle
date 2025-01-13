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


@pytest.mark.unit
class TestTransactionUtils(unittest.TestCase):

    def setUp(self):
        w3 = MagicMock()
        self.utils = TransactionUtils(w3)
        self.account = MagicMock(spec=LocalAccount)
        self.account.address = "0x123"

    def test_check_and_send_transaction_dry_mode(self):
        transaction = MagicMock()
        result = self.utils.check_and_send_transaction(transaction)

        self.assertIsNone(result)

    @patch('src.web3py.extensions.tx_utils.prompt', return_value=True)
    @patch('src.web3py.extensions.TransactionUtils._sign_and_send_transaction')
    def test_manual_transaction_processing(self, mock_sign_send, mock_prompt):
        transaction = MagicMock()
        params = {'from': self.account.address}
        account = MagicMock(spec=LocalAccount)

        self.utils._manual_tx_processing(transaction, params, account)

        mock_prompt.assert_called()
        mock_sign_send.assert_called_with(transaction, params, account)

    def test_check_transaction_reverted(self):
        transaction = MagicMock()
        transaction.call.side_effect = ValueError("Reverted")
        params = {'from': self.account.address}

        result = self.utils._check_transaction(transaction, params)

        self.assertFalse(result)

    @patch('src.web3py.extensions.TransactionUtils._estimate_gas', return_value=None)
    def test_get_transaction_params_without_gas(self, mock_estimate_gas):
        transaction = MagicMock(spec=ContractFunction)

        latest_block = {'baseFeePerGas': 10}
        self.utils.w3.eth.get_block.return_value = latest_block
        self.utils.w3.eth.get_transaction_count.return_value = 1
        self.utils.w3.eth.fee_history.return_value = {'reward': [[5]]}

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "MAX_PRIORITY_FEE", 20)
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 2)
            monkeypatch.setattr(variables, "PRIORITY_FEE_PERCENTILE", 10)
            params = self.utils._get_transaction_params(transaction, self.account)

            self.assertNotIn('gas', params)
            self.assertEqual(params['nonce'], 1)

    def test_estimate_gas_failure(self):
        transaction = MagicMock()
        transaction.estimate_gas.side_effect = ValueError("Execution reverted")
        gas = self.utils._estimate_gas(transaction, self.account)

        self.assertIsNone(gas)

    @patch('src.web3py.extensions.TransactionUtils._handle_sent_transaction')
    def test_sign_and_send_transaction(self, mock_handle_sent):
        transaction = MagicMock()
        params = {'from': self.account.address}
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

    def test_estimate_gas(self):
        tx = MagicMock()

        tx.estimate_gas = Mock(return_value=MAX_BLOCK_GAS_LIMIT * 2)
        gas_amount = self.utils._estimate_gas(tx, self.account)
        assert gas_amount == MAX_BLOCK_GAS_LIMIT

        tx.estimate_gas = Mock(return_value=100)
        gas_amount = self.utils._estimate_gas(tx, self.account)
        assert gas_amount == 100 + variables.TX_GAS_ADDITION

        tx.estimate_gas = Mock(side_effect=ContractLogicError())
        gas_amount = self.utils._estimate_gas(tx, self.account)
        assert gas_amount is None

    def test_manual_tx_processing(self):
        tx = MagicMock()
        input.get_input = Mock(return_value='y')
        self.utils._sign_and_send_transaction = Mock()
        self.utils._manual_tx_processing(tx, {}, self.account)
        self.utils._sign_and_send_transaction.assert_called_once()

    def test_manual_tx_processing_decline(self):
        tx = MagicMock()
        input.get_input = Mock(return_value='n')
        self.utils._sign_and_send_transaction = Mock()
        self.utils._manual_tx_processing(tx, {}, self.account)
        self.utils._sign_and_send_transaction.assert_not_called()

    def test_daemon_check_and_send_transaction(self):
        tx = MagicMock()
        input.get_input = Mock(return_value='n')
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "DAEMON", False)
            self.utils._sign_and_send_transaction = Mock()
            self.utils._get_transaction_params = Mock(return_value={})
            self.utils._check_transaction = Mock(return_value=True)
            self.utils.check_and_send_transaction(tx, self.account)
            self.utils._sign_and_send_transaction.assert_not_called()

    def test_find_transaction_timeout(self):
        self.utils.w3.eth.wait_for_transaction_receipt = Mock(side_effect=TimeExhausted())

        assert not self.utils._handle_sent_transaction('0x000001')

        self.utils.w3.eth.wait_for_transaction_receipt = Mock(
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

        assert self.utils._handle_sent_transaction('0x000001')

    def test_get_tx_params(self):
        gas_amount = 1000
        tx = MagicMock()
        tx.estimate_gas = Mock(return_value=gas_amount)

        self.utils.w3.eth.get_block = Mock(return_value={'baseFeePerGas': 20})
        self.utils.w3.eth.fee_history = Mock(return_value={'reward': [[5]]})
        self.utils.w3.eth.get_transaction_count = Mock(return_value=10)

        params = self.utils._get_transaction_params(tx, self.account)

        assert params['from'] == self.account.address
        assert params['maxFeePerGas'] == 20 * 2 + variables.MIN_PRIORITY_FEE
        assert params['maxPriorityFeePerGas'] == variables.MIN_PRIORITY_FEE
        assert params['nonce'] == 10
        assert params['gas'] == gas_amount + variables.TX_GAS_ADDITION

        tx.estimate_gas = Mock(side_effect=ContractLogicError())
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 1)
            params = self.utils._get_transaction_params(tx, self.account)

            assert params['maxPriorityFeePerGas'] == 5
            assert 'from' in params
            assert 'maxFeePerGas' in params
            assert 'nonce' in params
            assert 'gas' not in params

            self.utils.w3.eth.fee_history = Mock(return_value={'reward': [[1 * 10**18]]})
            params = self.utils._get_transaction_params(tx, self.account)

            assert params['maxPriorityFeePerGas'] == variables.MAX_PRIORITY_FEE
