import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from hexbytes import HexBytes

from src import variables
from src.web3py.extensions.telemetry_data_bus import TelemetryDataBus, EVENT_ID


@pytest.mark.unit
class TestTelemetryDataBus:
    def test___init____not_configured__skips_initialization(self):
        module = TelemetryDataBus('', '', 'accounting')

        assert not module.is_configured
        assert module._data_bus_w3 is None
        assert module._contract is None

    def test___init____missing_rpc__skips_initialization(self):
        module = TelemetryDataBus('', '0x1234567890abcdef1234567890abcdef12345678', 'accounting')

        assert not module.is_configured

    def test___init____missing_address__skips_initialization(self):
        module = TelemetryDataBus('http://localhost:8545', '', 'accounting')

        assert not module.is_configured

    def test_send_telemetry__not_configured__skips_send(self, caplog):
        module = TelemetryDataBus('', '', 'accounting')

        module.send_telemetry((1, 2, 3), b'\x00' * 32)

        assert 'DataBus telemetry is not configured. Skipping send.' in caplog.text

    def test_send_telemetry__no_account__skips_send(self, monkeypatch, caplog):
        module = TelemetryDataBus('', '', 'accounting')
        monkeypatch.setattr(variables, 'ACCOUNT', None)

        module.send_telemetry((1, 2, 3), b'\x00' * 32)

        assert 'DataBus telemetry is not configured. Skipping send.' in caplog.text
