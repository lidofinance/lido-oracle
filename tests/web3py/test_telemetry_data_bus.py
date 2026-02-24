import pytest

from src import variables
from src.web3py.extensions.telemetry_data_bus import TelemetryDataBus


@pytest.mark.unit
class TestTelemetryDataBus:
    def _create_module(self, web3, data_bus_rpc: str = '', data_bus_address: str = '', module_name: str = 'accounting'):
        return TelemetryDataBus(data_bus_rpc, data_bus_address, module_name, web3)

    def test___init____not_configured__logs_skipping(self, web3, caplog):
        self._create_module(web3)

        assert 'DataBus telemetry is not configured. Skipping initialization.' in caplog.text

    def test___init____missing_rpc__logs_skipping(self, web3, caplog):
        self._create_module(web3, data_bus_address='0x1234567890abcdef1234567890abcdef12345678')

        assert 'DataBus telemetry is not configured. Skipping initialization.' in caplog.text

    def test___init____missing_address__logs_skipping(self, web3, caplog):
        self._create_module(web3, data_bus_rpc='http://localhost:8545')

        assert 'DataBus telemetry is not configured. Skipping initialization.' in caplog.text

    def test_send_telemetry__not_configured__logs_skipping(self, web3, caplog):
        module = self._create_module(web3)

        module.send_telemetry((1, 2, 3), b'\x00' * 32)

        assert 'DataBus telemetry is not configured. Skipping send.' in caplog.text

    def test_send_telemetry__no_account__logs_skipping(self, web3, monkeypatch, caplog):
        module = self._create_module(web3)
        monkeypatch.setattr(variables, 'ACCOUNT', None)

        module.send_telemetry((1, 2, 3), b'\x00' * 32)

        assert 'DataBus telemetry is not configured. Skipping send.' in caplog.text
