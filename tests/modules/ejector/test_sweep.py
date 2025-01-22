import math
from unittest.mock import Mock, MagicMock

import pytest
import src.modules.ejector.sweep as sweep_module

from src.constants import MAX_WITHDRAWALS_PER_PAYLOAD, MIN_ACTIVATION_BALANCE
from src.modules.ejector.sweep import (
    get_sweep_delay_in_epochs_post_pectra,
    get_pending_partial_withdrawals,
    get_validators_withdrawals,
    Withdrawal,
)
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import BeaconStateView, PendingPartialWithdrawal, Validator
from src.types import Gwei
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import LidoValidatorFactory


@pytest.mark.unit
def test_get_sweep_delay_in_epochs_post_pectra(monkeypatch):
    # Create mock objects for state and spec
    state = Mock(spec=BeaconStateView)
    spec = Mock(spec=ChainConfig)
    spec.slots_per_epoch = 12
    predicted_withdrawals = 1000
    with monkeypatch.context() as m:
        m.setattr(
            sweep_module,
            "predict_withdrawals_number_in_sweep_cycle",
            Mock(return_value=predicted_withdrawals),
        )
        # Calculate delay
        result = get_sweep_delay_in_epochs_post_pectra(state, spec)

        # Assert the delay calculation is correct
        expected_delay = math.ceil(predicted_withdrawals / MAX_WITHDRAWALS_PER_PAYLOAD / int(spec.slots_per_epoch)) // 2
        assert result == expected_delay, f"Expected delay {expected_delay}, got {result}"


@pytest.fixture()
def fake_beacon_state_view():
    """Fixture to create a fake BeaconStateView."""
    validators = [
        LidoValidatorFactory.build_with_balance(Gwei(1000)),
        LidoValidatorFactory.build_with_balance(Gwei(MIN_ACTIVATION_BALANCE + 1)),
        LidoValidatorFactory.build_with_balance(Gwei(MIN_ACTIVATION_BALANCE + 12)),
    ]
    pending_partial_withdrawals = [
        PendingPartialWithdrawal(validator_index="0", amount=500, withdrawable_epoch=1),
        PendingPartialWithdrawal(validator_index="1", amount=700, withdrawable_epoch=1),
    ]
    return BeaconStateViewFactory.build_with_validators(
        validators=validators,
        pending_partial_withdrawals=pending_partial_withdrawals,
    )


@pytest.mark.unit
def test_get_pending_partial_withdrawals(fake_beacon_state_view):
    """Test for the `get_pending_partial_withdrawals` function."""
    result = get_pending_partial_withdrawals(fake_beacon_state_view)
    assert len(result) == 1, f"Expected 1 pending partial withdrawals, got {len(result)}"

    assert result[0].validator_index == 1, f"Expected validator_index 1, got {result[0].validator_index}"
    assert result[0].amount == 1, f"Expected amount 1 for validator 1, got {result[0].amount}"


@pytest.mark.unit
def test_get_validators_withdrawals(fake_beacon_state_view):
    """Test for the `get_validators_withdrawals` function."""
    result = get_validators_withdrawals(
        fake_beacon_state_view,
        [
            Withdrawal(validator_index=1, amount=1),
            Withdrawal(validator_index=2, amount=1),
            Withdrawal(validator_index=2, amount=1),
        ],
        32,
    )
    assert len(result) == 1, f"Expected 1 withdrawals, got {len(result)}"

    assert result[0].validator_index == 2, f"Expected validator_index 2, got {result[0].validator_index}"
    assert result[0].amount == 10, f"Expected amount 1 for validator 2, got {result[0].amount}"
