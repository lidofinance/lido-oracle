from unittest.mock import Mock, patch

import pytest

from src import variables
from src.constants import MAINNET_CHAIN_ID
from src.metrics.prometheus.basic import TELEMETRY_ACCOUNT_BALANCE
from src.web3py.extensions.telemetry_data_bus import TelemetryDataBus, TelemetryEventId


DUMMY_RPC = 'http://localhost:8545'
DUMMY_ADDRESS = '0x1234567890abcdef1234567890abcdef12345678'


@pytest.mark.unit
class TestTelemetryDataBus:
    def _create_module(self, web3, data_bus_rpc: str = '', data_bus_address: str = '', module_name: str = 'accounting'):
        return TelemetryDataBus(data_bus_rpc, data_bus_address, module_name, web3)

    def _mock_data_bus_w3(self, chain_id: int = 17000, code: bytes = b'') -> Mock:
        mock_w3 = Mock()
        mock_w3.eth.chain_id = chain_id
        mock_w3.eth.get_code.return_value = code
        return mock_w3

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
    def test___init____mainnet_chain_id__raises_mainnet_forbidden(self, mock_create_web3, web3):
        mock_create_web3.return_value = self._mock_data_bus_w3(chain_id=MAINNET_CHAIN_ID)

        with pytest.raises(TelemetryDataBus.MainnetForbiddenError):
            self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)

    @patch.object(TelemetryDataBus, '_create_web3')
    def test___init____no_code_at_address__raises_contract_not_deployed(self, mock_create_web3, web3):
        mock_create_web3.return_value = self._mock_data_bus_w3(chain_id=17000, code=b'')

        with pytest.raises(TelemetryDataBus.ContractNotDeployedError, match="No contract deployed"):
            self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)

    @patch('src.web3py.extensions.telemetry_data_bus.sign_and_send_transaction')
    @patch('src.web3py.extensions.telemetry_data_bus.build_transaction_params')
    @patch.object(TelemetryDataBus, '_validate')
    @patch.object(TelemetryDataBus, '_create_web3')
    def test_send_telemetry__configured__sends_transaction(
        self, mock_create_web3, mock_validate, mock_build_params, mock_sign_and_send, web3, caplog, monkeypatch
    ):
        monkeypatch.setattr(variables, 'ACCOUNT', Mock())
        mock_data_bus_w3 = Mock()
        mock_data_bus_w3.eth.get_balance.return_value = 10**18
        mock_create_web3.return_value = mock_data_bus_w3
        mock_contract = Mock()
        mock_data_bus_w3.eth.contract.return_value = mock_contract
        mock_tx = Mock()
        mock_contract.send_message.return_value = mock_tx
        mock_sign_and_send.return_value = b'\xab' * 32

        module = self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)
        report_data = (1, 2, 3)
        report_hash = b'\x00' * 32

        data = {'report_hash': '0x' + report_hash.hex(), 'report': list(report_data)}
        module.send_telemetry(TelemetryEventId.ORACLE_REPORT, data)

        mock_contract.send_message.assert_called_once()
        mock_build_params.assert_called_once()
        mock_sign_and_send.assert_called_once()
        assert 'DataBus telemetry sent.' in caplog.text
        mock_data_bus_w3.eth.get_balance.assert_called_once_with(variables.ACCOUNT.address)

    def test_send_telemetry__not_configured__logs_skipping(self, web3, caplog):
        module = self._create_module(web3)

        module.send_telemetry(TelemetryEventId.ORACLE_REPORT, {'report': [1, 2, 3]})

        assert 'DataBus telemetry is not configured. Skipping send.' in caplog.text

    @patch.object(TelemetryDataBus, '_validate')
    @patch.object(TelemetryDataBus, '_create_web3')
    def test_send_telemetry__no_account__skips_send(self, mock_create_web3, mock_validate, web3, caplog):
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
        monkeypatch.setattr(variables, 'ACCOUNT', account)
        mock_data_bus_w3 = Mock()
        mock_data_bus_w3.eth.get_balance.return_value = 10**18
        mock_create_web3.return_value = mock_data_bus_w3
        mock_data_bus_w3.eth.contract.return_value = Mock()

        module = self._create_module(web3, data_bus_rpc=DUMMY_RPC, data_bus_address=DUMMY_ADDRESS)
        module.update_account_balance_metric()

        assert TELEMETRY_ACCOUNT_BALANCE.labels(address=account.address)._value.get() == 10**18
