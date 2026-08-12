from unittest.mock import MagicMock

import pytest

from src.providers.execution.contracts.oracle_daemon_config import OracleDaemonConfigContract


@pytest.mark.unit
@pytest.mark.parametrize(
    ('method_name', 'config_key'),
    [
        ('bunker_finalization_delay_epochs', 'BUNKER_FINALIZATION_DELAY_EPOCHS'),
        ('bunker_base_slashing_impact_rate_ppm', 'BUNKER_BASE_SLASHING_IMPACT_RATE_PPM'),
        ('bunker_slashing_impact_threshold_ppm', 'BUNKER_SLASHING_IMPACT_THRESHOLD_PPM'),
    ],
)
def test_bunker_config_getter__configured_method__uses_expected_key(method_name: str, config_key: str) -> None:
    contract = MagicMock()
    contract._get.return_value = 42
    block_identifier = '0x1234'

    result = getattr(OracleDaemonConfigContract, method_name)(contract, block_identifier)

    assert result == 42
    contract._get.assert_called_once_with(config_key, block_identifier)
