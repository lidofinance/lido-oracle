import math
from unittest.mock import Mock

import pytest

import src.modules.ejector.sweep as sweep_module
from src.constants import MAX_WITHDRAWALS_PER_PAYLOAD, MIN_ACTIVATION_BALANCE
from src.modules.ejector.sweep import (
    get_pending_partial_withdrawals,
    get_sweep_delay_in_epochs,
    get_validators_withdrawals,
    Withdrawal,
)
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import BeaconStateView, PendingPartialWithdrawal
from src.types import Gwei
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


@pytest.mark.unit
def test_get_sweep_delay_in_epochs_post_electra(monkeypatch):
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
        result = get_sweep_delay_in_epochs(state, spec)

        # Assert the delay calculation is correct
        expected_delay = math.ceil(predicted_withdrawals / MAX_WITHDRAWALS_PER_PAYLOAD / spec.slots_per_epoch) // 2
        assert result == expected_delay, f"Expected delay {expected_delay}, got {result}"


@pytest.fixture()
def fake_beacon_state_view():
    """Fixture to create a fake BeaconStateView."""
    validators = [
        LidoValidatorFactory.build_with_balance(Gwei(1000)),
        LidoValidatorFactory.build_with_balance(Gwei(MIN_ACTIVATION_BALANCE + 1)),
        LidoValidatorFactory.build_with_balance(Gwei(MIN_ACTIVATION_BALANCE + 12)),
    ]
    min_withdraw_epoch = min([v.validator.withdrawable_epoch for v in validators])
    min_withdraw_slot = min_withdraw_epoch * 12 - 10
    pending_partial_withdrawals = [
        PendingPartialWithdrawal(validator_index=0, amount=500, withdrawable_epoch=1),
        PendingPartialWithdrawal(validator_index=1, amount=700, withdrawable_epoch=1),
    ]
    return BeaconStateViewFactory.build_with_validators(
        validators=validators,
        pending_partial_withdrawals=pending_partial_withdrawals,
        slashings=[],
        slot=min_withdraw_slot,
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


@pytest.mark.unit
def test_only_validators_withdrawals():
    """Test when there are only validators eligible for withdrawals."""

    mock_state = BeaconStateViewFactory.build(
        slot=32,
        validators=ValidatorStateFactory.batch(2, effective_balance=32_000_000_000, withdrawable_epoch=0),
        balances=[32_000_000_000] * 2,
        pending_partial_withdrawals=[],
        slashings=[],
    )
    result = sweep_module.predict_withdrawals_number_in_sweep_cycle(mock_state, 32)
    assert result == 2


@pytest.mark.unit
def test_combined_withdrawals():
    """Test when there are both partial and full withdrawals."""

    mock_state = BeaconStateViewFactory.build(
        slot=32,
        validators=ValidatorStateFactory.batch(10, effective_balance=32_000_000_000, exit_epoch=123),
        balances=[32_000_000_001] * 10,
        pending_partial_withdrawals=[],
        slashings=[],
    )
    result = sweep_module.predict_withdrawals_number_in_sweep_cycle(mock_state, 32)
    assert result == 10
