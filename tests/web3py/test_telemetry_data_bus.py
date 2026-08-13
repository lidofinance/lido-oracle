import importlib
import json
from unittest.mock import Mock, patch

import pytest
from hexbytes import HexBytes

from src import variables
from src.metrics.prometheus.basic import TELEMETRY_ACCOUNT_BALANCE
from src.utils.version import get_oracle_version
from src.web3py.extensions.telemetry_data_bus import (
    DataBusContractNotDeployedError,
    TelemetryDataBus,
    TelemetryEventId,
    TelemetrySendTimeoutError,
)


DUMMY_RPC = 'http://localhost:8545'
DUMMY_ADDRESS = '0x1234567890abcdef1234567890abcdef12345678'
DUMMY_MEMBER_PRIV_KEY = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'


@pytest.mark.unit
class TestTelemetryAccount:
    def test_telemetry_account_falls_back_to_account_when_no_telemetry_priv_key(self, monkeypatch):
        monkeypatch.setenv('MEMBER_PRIV_KEY', DUMMY_MEMBER_PRIV_KEY)
        monkeypatch.delenv('TELEMETRY_PRIV_KEY', raising=False)

        import src.variables as vars

        importlib.reload(vars)
        try:
            assert vars.TELEMETRY_ACCOUNT is not None
            assert vars.TELEMETRY_ACCOUNT == vars.ACCOUNT
        finally:
            monkeypatch.undo()
            importlib.reload(vars)

    def test_telemetry_account_uses_telemetry_priv_key_when_provided(self, monkeypatch):
        dummy_telemetry_key = '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        monkeypatch.setenv('MEMBER_PRIV_KEY', DUMMY_MEMBER_PRIV_KEY)
        monkeypatch.setenv('TELEMETRY_PRIV_KEY', dummy_telemetry_key)

        import src.variables as vars

        importlib.reload(vars)
        try:
            assert vars.TELEMETRY_ACCOUNT is not None
            assert vars.ACCOUNT is not None
            assert vars.TELEMETRY_ACCOUNT != vars.ACCOUNT
            assert vars.TELEMETRY_ACCOUNT.address != vars.ACCOUNT.address
        finally:
            monkeypatch.undo()
            importlib.reload(vars)


@pytest.mark.unit
class TestTelemetryDataBus:
    def _create_module(self, web3, data_bus_rpc: str = '', data_bus_address: str = '', module_name: str = 'accounting'):
        return TelemetryDataBus(data_bus_rpc, data_bus_address, module_name, web3)

    def _mock_data_bus_w3(self, chain_id: int = 17000, code: bytes = b'') -> Mock:
        mock_w3 = Mock()
        mock_w3.eth.chain_id = chain_id
        mock_w3.eth.get_code.return_value = code
        return mock_w3

    def _mock_send_retry_env(self) -> tuple[Mock, Mock, Mock]:
        w3 = Mock()
        account = Mock(address='0x0000000000000000000000000000000000000002')
        tx = Mock()
        return w3, account, tx

    def test___init____not_configured__logs_skipping(self, web3, caplog):
        self._create_module(web3)

        assert 'DataBus telemetry is not configured. Skipping initialization.' in caplog.text

    def test___init____missing_rpc__logs_skipping(self, web3, caplog):
        self._create_module(web3, data_bus_address=DUMMY_ADDRESS)

        assert 'DataBus telemetry is not configured. Skipping initialization.' in caplog.text

    def test___init____missing_address__logs_skipping(self, web3, caplog):
        self._create_module(web3, data_bus_rpc=DUMMY_RPC)

        assert 'DataBus telemetry is not configured. Skipping initialization.' in caplog.text

    @patch.object(TelemetryDataBus, '_create_web3')
    def test___init____no_code_at_address__raises_contract_not_deployed(self, mock_create_web3, web3):
        mock_create_web3.return_value = self._mock_data_bus_w3(chain_id=17000, code=b'')

        with pytest.raises(DataBusContractNotDeployedError, match="No contract deployed"):
            self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)

    @patch.object(TelemetryDataBus, '_send_telemetry')
    @patch.object(TelemetryDataBus, '_validate')
    @patch.object(TelemetryDataBus, '_create_web3')
    def test_send_telemetry__configured__sends_transaction(
        self, mock_create_web3, mock_validate, mock_send_telemetry, web3, caplog, monkeypatch
    ):
        monkeypatch.setattr(variables, 'TELEMETRY_ACCOUNT', Mock())
        mock_data_bus_w3 = Mock()
        mock_data_bus_w3.eth.get_balance.return_value = 10**18
        mock_create_web3.return_value = mock_data_bus_w3
        mock_contract = Mock()
        mock_data_bus_w3.eth.contract.return_value = mock_contract
        mock_tx = Mock()
        mock_contract.send_message.return_value = mock_tx
        mock_send_telemetry.return_value = b'\xab' * 32

        module = self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)
        report_data = (1, 2, 3)
        report_hash = b'\x00' * 32

        data = {'report_hash': '0x' + report_hash.hex(), 'report': list(report_data)}
        result = module.send_telemetry(TelemetryEventId.ORACLE_REPORT, data)

        assert result == b'\xab' * 32
        mock_contract.send_message.assert_called_once()
        payload = json.loads(mock_contract.send_message.call_args[0][1])
        assert payload['chain_id'] == web3.eth.chain_id
        assert payload['version'] == get_oracle_version()
        assert payload['module'] == 'accounting'
        assert payload['data'] == data
        mock_send_telemetry.assert_called_once_with(mock_tx, mock_data_bus_w3, variables.TELEMETRY_ACCOUNT)
        assert 'DataBus telemetry sent.' in caplog.text
        mock_data_bus_w3.eth.get_balance.assert_called_once_with(variables.TELEMETRY_ACCOUNT.address)

    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__tx_included_on_first_check__returns_tx_hash(
        self, mock_build_params, mock_sign_and_send, mock_sleep, web3, monkeypatch
    ):
        # attempt1: tx_hash is None so params['nonce'] is stored and the tx is sent without any inclusion
        # check. attempt2: nonce advanced (3 != 1) so the "no new tx yet" shortcut is skipped and inclusion
        # is confirmed via get_transaction.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 120)
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = [{'nonce': 1}, {'nonce': 2}]
        tx_hash = b'\xaa' * 32
        mock_sign_and_send.return_value = tx_hash
        w3_mock.eth.get_transaction.return_value = {'blockNumber': 42}

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == tx_hash
        assert mock_build_params.call_count == 2
        mock_sign_and_send.assert_called_once_with(w3_mock, tx, {'nonce': 1}, account)
        w3_mock.eth.get_transaction.assert_called_once_with(HexBytes(tx_hash))
        mock_sleep.assert_called_once()

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__pending_with_unchanged_nonce__never_checks_inclusion_and_returns_stale_hash_at_deadline(
        self, mock_build_params, mock_sign_and_send, mock_sleep, mock_monotonic, web3, monkeypatch
    ):
        # The "no new tx yet" shortcut (`tx_hash and params['nonce'] == nonce`)
        # fires BEFORE the inclusion check, so as long as the account's pending nonce doesn't advance,
        # get_transaction is never called at all -- the loop just sleeps until the deadline and returns
        # the already-sent hash via the trailing `if tx_hash: return tx_hash`, without ever confirming
        # it landed on-chain.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        # deadline=1; attempt1: build+send (no monotonic calls in try body); attempt2 & attempt3: same
        # nonce -> "no new tx yet" shortcut, no monotonic calls in that branch either; final check(2.0)<1
        # is False -> stop.
        mock_monotonic.side_effect = [0, 0.1, 0.2, 0.3, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.return_value = {'nonce': 3}
        tx_hash = b'\xbb' * 32
        mock_sign_and_send.return_value = tx_hash

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == tx_hash
        assert mock_build_params.call_count == 3
        mock_sign_and_send.assert_called_once()
        w3_mock.eth.get_transaction.assert_not_called()
        assert mock_sleep.call_count == 3

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__pending_with_changed_nonce__resigns_and_resends(
        self, mock_build_params, mock_sign_and_send, mock_sleep, mock_monotonic, web3, monkeypatch
    ):
        # attempt1: send with nonce 3. attempt2: nonce advanced to 4 -> inclusion checked, not yet mined
        # -> resigns and resends with nonce 4. attempt3: nonce unchanged (4 == 4) -> "no new tx yet"
        # shortcut, so the second send's inclusion is never re-checked within this run; deadline hits and
        # the (unconfirmed) second hash is returned.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        mock_monotonic.side_effect = [0, 0.1, 0.2, 0.3, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = [{'nonce': 3}, {'nonce': 4}, {'nonce': 4}]
        first_hash, second_hash = b'\xcc' * 32, b'\xdd' * 32
        mock_sign_and_send.side_effect = [first_hash, second_hash]
        w3_mock.eth.get_transaction.return_value = {'blockNumber': None}

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == second_hash
        assert mock_build_params.call_count == 3
        assert mock_sign_and_send.call_count == 2
        w3_mock.eth.get_transaction.assert_called_once_with(HexBytes(first_hash))
        assert mock_sleep.call_count == 3

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__build_params_fails_then_succeeds__retries_and_returns_tx_hash(
        self, mock_build_params, mock_sign_and_send, mock_sleep, mock_monotonic, web3, caplog, monkeypatch
    ):
        # attempt1: build_transaction_params raises before any send happens. attempt2: succeeds and sends.
        # attempt3: nonce advanced -> inclusion confirmed via get_transaction.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        mock_monotonic.side_effect = [0, 0.1, 0.15, 0.2, 0.3]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = [ValueError('nonce too low'), {'nonce': 1}, {'nonce': 2}]
        tx_hash = b'\xee' * 32
        mock_sign_and_send.return_value = tx_hash
        w3_mock.eth.get_transaction.return_value = {'blockNumber': 5}

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == tx_hash
        assert mock_build_params.call_count == 3
        mock_sign_and_send.assert_called_once()
        w3_mock.eth.get_transaction.assert_called_once_with(HexBytes(tx_hash))
        assert mock_sleep.call_count == 2
        assert 'Failed to send DataBus telemetry transaction. Will retry.' in caplog.text

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__sign_and_send_fails_then_succeeds__retries_and_returns_tx_hash(
        self, mock_build_params, mock_sign_and_send, mock_sleep, mock_monotonic, web3, caplog, monkeypatch
    ):
        # attempt1: build succeeds but sign_and_send_transaction raises, so tx_hash stays None. attempt2:
        # tx_hash is still None (the failed attempt never assigned it), so the send is retried cleanly --
        # not treated as "no new tx yet" and no inclusion check is attempted for a hash that was never
        # actually sent. Deadline hits before a third attempt could confirm inclusion.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        mock_monotonic.side_effect = [0, 0.1, 0.15, 0.2, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = [{'nonce': 1}, {'nonce': 2}]
        tx_hash = b'\xbb' * 32
        mock_sign_and_send.side_effect = [ValueError('replacement transaction underpriced'), tx_hash]

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == tx_hash
        assert mock_build_params.call_count == 2
        assert mock_sign_and_send.call_count == 2
        w3_mock.eth.get_transaction.assert_not_called()
        assert mock_sleep.call_count == 2
        assert 'Failed to send DataBus telemetry transaction. Will retry.' in caplog.text

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__get_transaction_raises_after_send__returns_stale_tx_hash_without_resending(
        self, mock_build_params, mock_sign_and_send, mock_sleep, mock_monotonic, web3, caplog, monkeypatch
    ):
        # Once a tx is sent and the nonce has advanced, an exception from get_transaction is caught by the
        # broad except -- it's raised before `nonce = params.get('nonce')` is reached, so `nonce` is never
        # updated and no resend is attempted. On timeout the stale (unconfirmed) hash is returned as-is.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        mock_monotonic.side_effect = [0, 0.1, 0.2, 0.25, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = [{'nonce': 1}, {'nonce': 2}]
        tx_hash = b'\xaa' * 32
        mock_sign_and_send.return_value = tx_hash
        w3_mock.eth.get_transaction.side_effect = ValueError('not found')

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == tx_hash
        assert mock_build_params.call_count == 2
        mock_sign_and_send.assert_called_once()
        w3_mock.eth.get_transaction.assert_called_once_with(HexBytes(tx_hash))
        assert 'Failed to send DataBus telemetry transaction. Will retry.' in caplog.text

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__build_params_raises_while_tx_hash_already_set__returns_stale_tx_hash_without_resending(
        self, mock_build_params, mock_sign_and_send, mock_sleep, mock_monotonic, web3, caplog, monkeypatch
    ):
        # Same class of defect as the get_transaction case above, but the transient failure happens in
        # build_transaction_params itself (e.g. a flaky RPC call) on a later poll, after a tx_hash is
        # already set. The exception is caught before the inclusion check ever runs.
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        mock_monotonic.side_effect = [0, 0.1, 0.2, 0.25, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = [{'nonce': 1}, ConnectionError('rpc unavailable')]
        tx_hash = b'\xaa' * 32
        mock_sign_and_send.return_value = tx_hash

        module = self._create_module(web3)
        result = module._send_telemetry(tx, w3_mock, account)

        assert result == tx_hash
        assert mock_build_params.call_count == 2
        mock_sign_and_send.assert_called_once()
        w3_mock.eth.get_transaction.assert_not_called()
        assert 'Failed to send DataBus telemetry transaction. Will retry.' in caplog.text

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__deadline_exceeded_inside_except__breaks_and_raises(
        self, mock_build_params, mock_sleep, mock_monotonic, web3, caplog, monkeypatch
    ):
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        # deadline=1; while-check(0.5)<1 -> attempt, raises; remaining calc uses monotonic()=1.5 ->
        # remaining=-0.5 (logged as 0 via max(remaining, 0)); next while-check(2.0)<1 is False -> stop.
        mock_monotonic.side_effect = [0, 0.5, 1.5, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = ValueError('boom')

        module = self._create_module(web3)

        with pytest.raises(TelemetrySendTimeoutError, match="Timed out sending DataBus telemetry transaction"):
            module._send_telemetry(tx, w3_mock, account)

        mock_build_params.assert_called_once()
        mock_sleep.assert_called_once()
        assert 'Failed to send DataBus telemetry transaction. Will retry.' in caplog.text

    @patch('src.web3py.extensions.telemetry_data_bus.time.monotonic')
    @patch('src.web3py.extensions.telemetry_data_bus.time.sleep')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    def test__send_with_retry__all_attempts_fail__raises_send_timeout_error(
        self, mock_build_params, mock_sleep, mock_monotonic, web3, caplog, monkeypatch
    ):
        monkeypatch.setattr(variables, 'TELEMETRY_TX_SEND_TIMEOUT_SECONDS', 1)
        # deadline=1; iter1 check(0.1)<1 -> attempt; remaining calc(0.2); iter2 check(2.0)<1 is False -> stop.
        mock_monotonic.side_effect = [0, 0.1, 0.2, 2.0]
        w3_mock, account, tx = self._mock_send_retry_env()
        mock_build_params.side_effect = ValueError('nonce too low')

        module = self._create_module(web3)

        with pytest.raises(TelemetrySendTimeoutError, match="Timed out sending DataBus telemetry transaction"):
            module._send_telemetry(tx, w3_mock, account)

        assert mock_build_params.call_count == 1
        mock_sleep.assert_called_once()
        assert 'Failed to send DataBus telemetry transaction. Will retry.' in caplog.text

    def test_send_telemetry__not_configured__logs_skipping(self, web3, caplog):
        module = self._create_module(web3)

        module.send_telemetry(TelemetryEventId.ORACLE_REPORT, {'report': [1, 2, 3]})

        assert 'DataBus telemetry is not configured. Skipping send.' in caplog.text

    @patch.object(TelemetryDataBus, '_validate')
    @patch.object(TelemetryDataBus, '_create_web3')
    def test_send_telemetry__no_account__skips_send(self, mock_create_web3, mock_validate, web3, caplog, monkeypatch):
        monkeypatch.setattr(variables, 'TELEMETRY_ACCOUNT', None)
        mock_data_bus_w3 = Mock()
        mock_create_web3.return_value = mock_data_bus_w3
        mock_data_bus_w3.eth.contract.return_value = Mock()

        module = self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)
        module.send_telemetry(TelemetryEventId.ORACLE_REPORT, {'report': [1, 2, 3]})

        assert 'No account provided. Skipping telemetry send.' in caplog.text

    @patch.object(TelemetryDataBus, '_validate')
    @patch.object(TelemetryDataBus, '_create_web3')
    def test_update_account_balance_metric__configured__sets_metric(
        self, mock_create_web3, mock_validate, web3, monkeypatch
    ):
        account = Mock(address='0x0000000000000000000000000000000000000001')
        monkeypatch.setattr(variables, 'TELEMETRY_ACCOUNT', account)
        mock_data_bus_w3 = Mock()
        mock_data_bus_w3.eth.get_balance.return_value = 10**18
        mock_create_web3.return_value = mock_data_bus_w3
        mock_data_bus_w3.eth.contract.return_value = Mock()

        module = self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)
        module.update_telemetry_account_balance_metric()

        assert TELEMETRY_ACCOUNT_BALANCE.labels(address=account.address)._value.get() == 10**18
