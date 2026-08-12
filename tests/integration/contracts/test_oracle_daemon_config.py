import pytest

from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_oracle_daemon_config_contract(oracle_daemon_config_contract, caplog):
    check_contract(
        oracle_daemon_config_contract,
        [
            (
                'prediction_duration_in_slots',
                None,
                lambda response: check_value_type(response, int),
            ),
            # (
            #    'exit_events_lookback_window_in_slots',
            #    None,
            #    lambda response: check_value_type(response, int),
            # )
        ],
        caplog,
    )
