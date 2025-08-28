from unittest.mock import MagicMock, patch

import pytest
from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from web3.exceptions import ContractLogicError, TimeExhausted

from src import variables
from src.utils import input
from src.web3py.contract_tweak import ContractFunction
from src.web3py.extensions import TransactionUtils


@pytest.fixture
def fake_transaction_utils():
    w3 = MagicMock()
    utils = TransactionUtils(w3)
    account = MagicMock(spec=LocalAccount)
    account.address = "0x123"
    return utils, account


@pytest.mark.unit
class TestTransactionUtils:
    def test_check_and_send_transaction_dry_mode(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        result = utils.check_and_send_transaction(transaction)

        assert result is None

    @patch('src.web3py.extensions.tx_utils.prompt', return_value=True)
    @patch('src.web3py.extensions.TransactionUtils._sign_and_send_transaction')
    def test_manual_transaction_processing(self, mock_sign_send, mock_prompt, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        params = {'from': account.address}
        account = MagicMock(spec=LocalAccount)

        utils._manual_tx_processing(transaction, params, account)

        mock_prompt.assert_called()
        mock_sign_send.assert_called_with(transaction, params, account)

    def test_check_transaction_reverted(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        transaction.call.side_effect = ValueError("Reverted")
        params = {'from': account.address}

        result = utils._check_transaction(transaction, params)

        assert result is False

    @patch('src.web3py.extensions.TransactionUtils._estimate_gas', return_value=None)
    def test_get_transaction_params_without_gas(self, mock_estimate_gas, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock(spec=ContractFunction)

        latest_block = {'baseFeePerGas': 10}
        utils.w3.eth.get_block.return_value = latest_block
        utils.w3.eth.get_transaction_count.return_value = 1
        utils.w3.eth.fee_history.return_value = {'reward': [[5]]}

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "MAX_PRIORITY_FEE", 20)
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 2)
            monkeypatch.setattr(variables, "PRIORITY_FEE_PERCENTILE", 10)
            params = utils._get_transaction_params(transaction, account)

            assert 'gas' not in params
            assert params['nonce'] == 1

    def test_estimate_gas_failure(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        transaction.estimate_gas.side_effect = ValueError("Execution reverted")
        gas = utils._estimate_gas(transaction, account)

        assert gas is None

    @patch('src.web3py.extensions.TransactionUtils._handle_sent_transaction')
    def test_sign_and_send_transaction(self, mock_handle_sent, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        params = {'from': account.address}
        account.key = "dummy_key"

        built_tx = {'key': 'value'}
        transaction.build_transaction.return_value = built_tx

        signed_tx = MagicMock()
        signed_tx.raw_transaction = HexBytes("0xabc")
        utils.w3.eth.account.sign_transaction.return_value = signed_tx

        tx_hash = HexBytes("0x123")
        utils.w3.eth.send_raw_transaction.return_value = tx_hash

        utils._sign_and_send_transaction(transaction, params, account)

        utils.w3.eth.send_raw_transaction.assert_called_with(signed_tx.raw_transaction)
        mock_handle_sent.assert_called_with(tx_hash)

    def test_estimate_gas(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()

        tx.estimate_gas = MagicMock(return_value=100)
        gas_amount = utils._estimate_gas(tx, account)
        assert gas_amount == 100 + variables.TX_GAS_ADDITION

        tx.estimate_gas = MagicMock(side_effect=ContractLogicError())
        gas_amount = utils._estimate_gas(tx, account)
        assert gas_amount is None

    def test_manual_tx_processing(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()
        input.get_input = MagicMock(return_value='y')
        utils._sign_and_send_transaction = MagicMock()
        utils._manual_tx_processing(tx, {}, account)
        utils._sign_and_send_transaction.assert_called_once()

    def test_manual_tx_processing_decline(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()
        input.get_input = MagicMock(return_value='n')
        utils._sign_and_send_transaction = MagicMock()
        utils._manual_tx_processing(tx, {}, account)
        utils._sign_and_send_transaction.assert_not_called()

    def test_daemon_check_and_send_transaction(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()
        input.get_input = MagicMock(return_value='n')
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "DAEMON", False)
            utils._sign_and_send_transaction = MagicMock()
            utils._get_transaction_params = MagicMock(return_value={})
            utils._check_transaction = MagicMock(return_value=True)
            utils.check_and_send_transaction(tx, account)
            utils._sign_and_send_transaction.assert_not_called()

    def test_find_transaction_timeout(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        utils.w3.eth.wait_for_transaction_receipt = MagicMock(side_effect=TimeExhausted())

        assert not utils._handle_sent_transaction('0x000001')

        utils.w3.eth.wait_for_transaction_receipt = MagicMock(
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

        assert utils._handle_sent_transaction('0x000001')

    def test_get_tx_params(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        gas_amount = 1000
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=gas_amount)

        utils.w3.eth.get_block = MagicMock(return_value={'baseFeePerGas': 20})
        utils.w3.eth.fee_history = MagicMock(return_value={'reward': [[5]]})
        utils.w3.eth.get_transaction_count = MagicMock(return_value=10)

        params = utils._get_transaction_params(tx, account)

        assert params['from'] == account.address
        assert params['maxFeePerGas'] == 20 * 2 + variables.MIN_PRIORITY_FEE
        assert params['maxPriorityFeePerGas'] == variables.MIN_PRIORITY_FEE
        assert params['nonce'] == 10
        assert params['gas'] == gas_amount + variables.TX_GAS_ADDITION

        tx.estimate_gas = MagicMock(side_effect=ContractLogicError())
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 1)
            params = utils._get_transaction_params(tx, account)

            assert params['maxPriorityFeePerGas'] == 5
            assert 'from' in params
            assert 'maxFeePerGas' in params
            assert 'nonce' in params
            assert 'gas' not in params

            utils.w3.eth.fee_history = MagicMock(return_value={'reward': [[1 * 10**18]]})
            params = utils._get_transaction_params(tx, account)

            assert params['maxPriorityFeePerGas'] == variables.MAX_PRIORITY_FEE
