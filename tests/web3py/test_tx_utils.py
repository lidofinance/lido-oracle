from unittest.mock import MagicMock, patch

import pytest
from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from web3.exceptions import ContractLogicError, TimeExhausted

from src import variables
from src.constants import EIP_7825_TX_GAS_LIMIT, EIP_8037_TX_MAX_TOTAL_GAS_LIMIT
from src.utils import input
from src.utils.transaction import GasEstimateAboveCap, build_transaction_params, estimate_gas, tx_gas_cap
from src.web3py.extensions import TransactionUtils


GAS_CAP = EIP_7825_TX_GAS_LIMIT
GENESIS_TIME = 1_000
SECONDS_PER_SLOT = 12
SLOTS_PER_EPOCH = 32
GLOAS_FORK_EPOCH = 100


def timestamp_at_epoch(epoch: int) -> int:
    return GENESIS_TIME + epoch * SLOTS_PER_EPOCH * SECONDS_PER_SLOT


@pytest.fixture
def fake_transaction_utils():
    w3 = MagicMock()
    account = MagicMock(spec=LocalAccount)
    account.address = "0x123"
    w3.signer.active_signer = account
    w3.signer.is_delegated = False
    w3.cc.get_config_spec.return_value = MagicMock(SECONDS_PER_SLOT=SECONDS_PER_SLOT)
    w3.cc.get_genesis.return_value.genesis_time = GENESIS_TIME
    w3.cc.is_gloas_slot.side_effect = lambda slot: slot // SLOTS_PER_EPOCH >= GLOAS_FORK_EPOCH
    w3.eth.get_block.return_value = {'baseFeePerGas': 10, 'timestamp': timestamp_at_epoch(0)}
    utils = TransactionUtils(w3)
    return utils, account


@pytest.mark.unit
class TestTransactionUtils:
    def test_check_and_send_transaction_dry_mode(self, fake_transaction_utils):
        utils, _ = fake_transaction_utils
        utils.w3.signer.active_signer = None
        transaction = MagicMock()

        result = utils.check_and_send_transaction(transaction)

        assert result is None

    @patch('src.web3py.extensions.tx_utils.prompt', return_value=True)
    @patch('src.web3py.extensions.TransactionUtils._send_transaction')
    def test_manual_transaction_processing(self, mock_send, mock_prompt, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        params = {'from': account.address}
        account = MagicMock(spec=LocalAccount)

        utils._manual_tx_processing(transaction, params, account)

        mock_prompt.assert_called()
        mock_send.assert_called_with(transaction, params, account)

    def test_check_transaction_reverted(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        transaction.call.side_effect = ValueError("Reverted")
        params = {'from': account.address}

        result = utils._check_transaction(transaction, params)

        assert result is False

    @patch('src.utils.transaction.estimate_gas', return_value=None)
    def test_get_transaction_params_without_gas(self, mock_estimate_gas, fake_transaction_utils):
        utils, account = fake_transaction_utils

        latest_block = {'baseFeePerGas': 10}
        utils.w3.eth.get_block.return_value = latest_block
        utils.w3.eth.get_transaction_count.return_value = 1
        utils.w3.eth.fee_history.return_value = {'reward': [[5]]}

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "MAX_PRIORITY_FEE", 20)
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 2)
            monkeypatch.setattr(variables, "PRIORITY_FEE_PERCENTILE", 10)
            params = build_transaction_params(utils.w3, MagicMock(), account, GAS_CAP)

            assert 'gas' not in params
            assert params['nonce'] == 1

    def test_estimate_gas_failure(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        transaction = MagicMock()
        transaction.estimate_gas.side_effect = ValueError("Execution reverted")
        gas = estimate_gas(transaction, account, GAS_CAP)

        assert gas is None

    @patch('src.web3py.extensions.TransactionUtils._handle_sent_transaction')
    def test_send_transaction(self, mock_handle_sent, fake_transaction_utils):
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

        utils._send_transaction(transaction, params, account)

        utils.w3.eth.send_raw_transaction.assert_called_with(signed_tx.raw_transaction)
        mock_handle_sent.assert_called_with(HexBytes(tx_hash))

    def test_estimate_gas(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()

        tx.estimate_gas = MagicMock(return_value=100)
        gas_amount = estimate_gas(tx, account, GAS_CAP)
        assert gas_amount == 100 + variables.TX_GAS_ADDITION

        tx.estimate_gas = MagicMock(side_effect=ContractLogicError())
        gas_amount = estimate_gas(tx, account, GAS_CAP)
        assert gas_amount is None

    def test_estimate_gas__estimate_with_addition_below_cap__returns_estimate_with_addition(
        self, fake_transaction_utils
    ):
        # Arrange
        _, account = fake_transaction_utils
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=GAS_CAP - variables.TX_GAS_ADDITION)

        # Act
        gas_amount = estimate_gas(tx, account, GAS_CAP)

        # Assert
        assert gas_amount == GAS_CAP

    def test_estimate_gas__estimate_with_addition_above_cap__clamped_to_cap(self, fake_transaction_utils):
        # Arrange
        _, account = fake_transaction_utils
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=GAS_CAP - variables.TX_GAS_ADDITION + 1)

        # Act
        gas_amount = estimate_gas(tx, account, GAS_CAP)

        # Assert
        assert gas_amount == GAS_CAP

    def test_estimate_gas__estimate_equals_cap__clamped_to_cap(self, fake_transaction_utils):
        # Arrange
        _, account = fake_transaction_utils
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=GAS_CAP)

        # Act
        gas_amount = estimate_gas(tx, account, GAS_CAP)

        # Assert
        assert gas_amount == GAS_CAP

    def test_estimate_gas__estimate_above_cap__raises_and_logs_error(self, fake_transaction_utils, caplog):
        # Arrange
        _, account = fake_transaction_utils
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=GAS_CAP + 1)

        # Act
        with pytest.raises(GasEstimateAboveCap):
            estimate_gas(tx, account, GAS_CAP)

        # Assert
        errors = [record for record in caplog.records if record.levelname == 'ERROR']
        assert len(errors) == 1
        assert errors[0].msg['estimated_gas'] == GAS_CAP + 1
        assert errors[0].msg['gas_cap'] == GAS_CAP

    @pytest.mark.parametrize(
        ('is_glamsterdam', 'expected_cap'),
        [(False, EIP_7825_TX_GAS_LIMIT), (True, EIP_8037_TX_MAX_TOTAL_GAS_LIMIT)],
    )
    def test_tx_gas_cap__no_operator_limit__returns_fork_cap(self, monkeypatch, is_glamsterdam, expected_cap):
        # Arrange
        monkeypatch.setattr(variables, 'TX_GAS_LIMIT', None)

        # Act
        cap = tx_gas_cap(is_glamsterdam)

        # Assert
        assert cap == expected_cap

    @pytest.mark.parametrize('is_glamsterdam', [False, True])
    def test_tx_gas_cap__operator_limit_below_fork_cap__returns_operator_limit(self, monkeypatch, is_glamsterdam):
        # Arrange
        monkeypatch.setattr(variables, 'TX_GAS_LIMIT', 10_000_000)

        # Act
        cap = tx_gas_cap(is_glamsterdam)

        # Assert
        assert cap == 10_000_000

    def test_tx_gas_cap__operator_limit_above_pre_glamsterdam_cap__returns_eip_7825_cap(self, monkeypatch):
        # Arrange
        monkeypatch.setattr(variables, 'TX_GAS_LIMIT', EIP_8037_TX_MAX_TOTAL_GAS_LIMIT)

        # Act
        cap = tx_gas_cap(is_glamsterdam=False)

        # Assert
        assert cap == EIP_7825_TX_GAS_LIMIT

    @pytest.mark.parametrize(
        ('epoch', 'expected_cap'),
        [
            (GLOAS_FORK_EPOCH - 1, EIP_7825_TX_GAS_LIMIT),
            (GLOAS_FORK_EPOCH, EIP_8037_TX_MAX_TOTAL_GAS_LIMIT),
        ],
    )
    @patch('src.web3py.extensions.tx_utils.build_transaction_params', return_value={})
    def test_check_and_send_transaction__latest_block_epoch__builds_params_with_fork_cap(
        self, mock_build_params, fake_transaction_utils, monkeypatch, epoch, expected_cap
    ):
        # Arrange
        utils, account = fake_transaction_utils
        monkeypatch.setattr(variables, 'TX_GAS_LIMIT', None)
        utils.w3.eth.get_block.return_value = {'baseFeePerGas': 10, 'timestamp': timestamp_at_epoch(epoch) + 5}
        utils._check_transaction = MagicMock(return_value=False)
        tx = MagicMock()

        # Act
        utils.check_and_send_transaction(tx)

        # Assert
        utils.w3.cc.is_gloas_slot.assert_called_once_with(epoch * SLOTS_PER_EPOCH)
        mock_build_params.assert_called_once_with(utils.w3, tx, account, expected_cap)

    @pytest.mark.parametrize(
        ('epoch', 'estimate'),
        [
            (GLOAS_FORK_EPOCH - 1, EIP_7825_TX_GAS_LIMIT + 1),
            (GLOAS_FORK_EPOCH, EIP_8037_TX_MAX_TOTAL_GAS_LIMIT + 1),
        ],
    )
    def test_check_and_send_transaction__estimate_above_fork_cap__not_sent(
        self, fake_transaction_utils, monkeypatch, epoch, estimate
    ):
        # Arrange
        utils, _ = fake_transaction_utils
        monkeypatch.setattr(variables, 'TX_GAS_LIMIT', None)
        monkeypatch.setattr(variables, 'DAEMON', True)
        utils.w3.eth.get_block.return_value = {'baseFeePerGas': 10, 'timestamp': timestamp_at_epoch(epoch)}
        utils.w3.eth.fee_history.return_value = {'reward': [[5]]}
        utils.w3.eth.get_transaction_count.return_value = 1
        utils._check_transaction = MagicMock(return_value=True)
        utils._send_transaction = MagicMock()
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=estimate)

        # Act
        result = utils.check_and_send_transaction(tx)

        # Assert
        assert result is None
        utils._check_transaction.assert_not_called()
        utils._send_transaction.assert_not_called()

    def test_check_and_send_transaction__estimate_above_pre_glamsterdam_cap_after_fork__sent_with_estimate(
        self, fake_transaction_utils, monkeypatch
    ):
        # Arrange
        utils, account = fake_transaction_utils
        estimate = EIP_7825_TX_GAS_LIMIT + 1
        monkeypatch.setattr(variables, 'TX_GAS_LIMIT', None)
        monkeypatch.setattr(variables, 'DAEMON', True)
        utils.w3.eth.get_block.return_value = {'baseFeePerGas': 10, 'timestamp': timestamp_at_epoch(GLOAS_FORK_EPOCH)}
        utils.w3.eth.fee_history.return_value = {'reward': [[5]]}
        utils.w3.eth.get_transaction_count.return_value = 1
        utils._check_transaction = MagicMock(return_value=True)
        utils._send_transaction = MagicMock()
        tx = MagicMock()
        tx.estimate_gas = MagicMock(return_value=estimate)

        # Act
        utils.check_and_send_transaction(tx)

        # Assert
        sent_params = utils._send_transaction.call_args.args[1]
        assert sent_params['gas'] == estimate + variables.TX_GAS_ADDITION
        assert sent_params['gas'] > EIP_7825_TX_GAS_LIMIT

    def test_manual_tx_processing(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()
        input.get_input = MagicMock(return_value='y')
        receipt = MagicMock()
        utils._send_transaction = MagicMock(return_value=receipt)
        result = utils._manual_tx_processing(tx, {}, account)
        utils._send_transaction.assert_called_once()
        assert result is receipt

    def test_manual_tx_processing_decline(self, fake_transaction_utils):
        utils, account = fake_transaction_utils
        tx = MagicMock()
        input.get_input = MagicMock(return_value='n')
        utils._send_transaction = MagicMock()
        utils._manual_tx_processing(tx, {}, account)
        utils._send_transaction.assert_not_called()

    @patch('src.web3py.extensions.tx_utils.build_transaction_params', return_value={})
    def test_daemon_check_and_send_transaction(self, mock_build_params, fake_transaction_utils):
        utils, _ = fake_transaction_utils
        tx = MagicMock()
        input.get_input = MagicMock(return_value='n')
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "DAEMON", False)
            utils._send_transaction = MagicMock()
            utils._check_transaction = MagicMock(return_value=True)
            utils.check_and_send_transaction(tx)
            utils._send_transaction.assert_not_called()

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

        params = build_transaction_params(utils.w3, tx, account, GAS_CAP)

        assert params['from'] == account.address
        assert params['maxFeePerGas'] == 20 * 2 + variables.MIN_PRIORITY_FEE
        assert params['maxPriorityFeePerGas'] == variables.MIN_PRIORITY_FEE
        assert params['nonce'] == 10
        assert params['gas'] == gas_amount + variables.TX_GAS_ADDITION

        tx.estimate_gas = MagicMock(side_effect=ContractLogicError())
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "MIN_PRIORITY_FEE", 1)
            params = build_transaction_params(utils.w3, tx, account, GAS_CAP)

            assert params['maxPriorityFeePerGas'] == 5
            assert 'from' in params
            assert 'maxFeePerGas' in params
            assert 'nonce' in params
            assert 'gas' not in params

            utils.w3.eth.fee_history = MagicMock(return_value={'reward': [[1 * 10**18]]})
            params = build_transaction_params(utils.w3, tx, account, GAS_CAP)

            assert params['maxPriorityFeePerGas'] == variables.MAX_PRIORITY_FEE

    @patch('src.web3py.extensions.tx_utils.build_transaction_params', return_value={})
    def test_check_and_send_transaction__is_delegated__wraps_call(self, mock_build_params, fake_transaction_utils):
        # Arrange
        utils, account = fake_transaction_utils
        utils.w3.signer.is_delegated = True

        wrapped_transaction = MagicMock()
        utils.w3.signer.wrap_call_for_delegation.return_value = wrapped_transaction

        utils._check_transaction = MagicMock(return_value=True)
        utils._send_transaction = MagicMock()

        original_transaction = MagicMock()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "DAEMON", True)

            # Act
            utils.check_and_send_transaction(original_transaction)

            # Assert
            utils.w3.signer.wrap_call_for_delegation.assert_called_once_with(original_transaction)
            utils._check_transaction.assert_called_once_with(wrapped_transaction, {})
            utils._send_transaction.assert_called_once_with(wrapped_transaction, {}, account)

    @patch('src.web3py.extensions.tx_utils.build_transaction_params', return_value={})
    def test_check_and_send_transaction__not_delegated__does_not_wrap(self, mock_build_params, fake_transaction_utils):
        # Arrange
        utils, account = fake_transaction_utils
        utils.w3.signer.is_delegated = False

        utils._check_transaction = MagicMock(return_value=True)
        utils._send_transaction = MagicMock()

        original_transaction = MagicMock()

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(variables, "DAEMON", True)

            # Act
            utils.check_and_send_transaction(original_transaction)

            # Assert
            utils.w3.signer.wrap_call_for_delegation.assert_not_called()
            utils._check_transaction.assert_called_once_with(original_transaction, {})
            utils._send_transaction.assert_called_once_with(original_transaction, {}, account)

    def test_check_and_send_transaction__delegation_wrap_fails__propagates_error(self, fake_transaction_utils):
        # Arrange
        utils, _ = fake_transaction_utils
        utils.w3.signer.is_delegated = True
        utils.w3.signer.wrap_call_for_delegation.side_effect = RuntimeError("Delegation not configured")

        original_transaction = MagicMock()

        # Act & Assert
        with pytest.raises(RuntimeError, match="Delegation not configured"):
            utils.check_and_send_transaction(original_transaction)
