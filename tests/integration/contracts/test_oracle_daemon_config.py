import pytest

from src.constants import TOTAL_BASIS_POINTS
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_oracle_daemon_config_contract(oracle_daemon_config_contract, caplog):
    check_contract(
        oracle_daemon_config_contract,
        [
            (
                'normalized_cl_reward_mistake_rate_bp',
                None,
                lambda response: check_value_type(response, int) and response < TOTAL_BASIS_POINTS,
            ),
            (
                'rebase_check_nearest_epoch_distance',
                None,
                lambda response: check_value_type(response, int),
            ),
            (
                'rebase_check_distant_epoch_distance',
                None,
                lambda response: check_value_type(response, int),
            ),
            (
                'prediction_duration_in_slots',
                None,
                lambda response: check_value_type(response, int),
            ),
            (
                'finalization_max_negative_rebase_epoch_shift',
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
