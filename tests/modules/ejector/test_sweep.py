import math
from unittest.mock import Mock

import pytest

import src.modules.oracles.ejector.sweep as sweep_module
from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP,
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_ACTIVATION_BALANCE,
)
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.sweep import (
    Withdrawal,
    get_pending_partial_withdrawals,
    get_sweep_delay_in_epochs,
    get_validators_withdrawals,
)
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


@pytest.mark.unit
def test_get_pending_partial_withdrawals_filters_exiting_validator():
    """Validators with exit_epoch != FAR_FUTURE_EPOCH are excluded from pending partial withdrawals."""
    validator = LidoValidatorFactory.build(
        balance=Gwei(MIN_ACTIVATION_BALANCE + 100),
        validator=ValidatorStateFactory.build(
            effective_balance=MIN_ACTIVATION_BALANCE,
            exit_epoch=10,  # Validator is exiting — not FAR_FUTURE_EPOCH
        ),
    )
    state = BeaconStateViewFactory.build_with_validators(
        validators=[validator],
        pending_partial_withdrawals=[PendingPartialWithdrawal(validator_index=0, amount=100, withdrawable_epoch=1)],
        slashings=[],
        slot=32,
    )
    result = get_pending_partial_withdrawals(state)
    assert result == [], "Exiting validator should be excluded from pending partial withdrawals"


@pytest.mark.unit
def test_get_pending_partial_withdrawals_filters_low_effective_balance():
    """Validators with effective_balance < MIN_ACTIVATION_BALANCE are excluded."""
    validator = LidoValidatorFactory.build(
        balance=Gwei(MIN_ACTIVATION_BALANCE + 100),
        validator=ValidatorStateFactory.build(
            effective_balance=MIN_ACTIVATION_BALANCE - 1,  # Below the minimum threshold
            exit_epoch=FAR_FUTURE_EPOCH,
        ),
    )
    state = BeaconStateViewFactory.build_with_validators(
        validators=[validator],
        pending_partial_withdrawals=[PendingPartialWithdrawal(validator_index=0, amount=100, withdrawable_epoch=1)],
        slashings=[],
        slot=32,
    )
    result = get_pending_partial_withdrawals(state)
    assert result == [], "Validator with effective_balance < MIN_ACTIVATION_BALANCE should be excluded"


@pytest.mark.unit
def test_get_pending_partial_withdrawals_filters_no_excess_balance():
    """Validators with balance == MIN_ACTIVATION_BALANCE have no excess to withdraw."""
    validator = LidoValidatorFactory.build(
        balance=Gwei(MIN_ACTIVATION_BALANCE),  # Exactly at minimum — no excess balance
        validator=ValidatorStateFactory.build(
            effective_balance=MIN_ACTIVATION_BALANCE,
            exit_epoch=FAR_FUTURE_EPOCH,
        ),
    )
    state = BeaconStateViewFactory.build_with_validators(
        validators=[validator],
        pending_partial_withdrawals=[PendingPartialWithdrawal(validator_index=0, amount=100, withdrawable_epoch=1)],
        slashings=[],
        slot=32,
    )
    result = get_pending_partial_withdrawals(state)
    assert result == [], "Validator with balance == MIN_ACTIVATION_BALANCE has no excess balance"


@pytest.mark.unit
def test_predict_withdrawals_with_pending_partials_ratio(monkeypatch):
    """Pending partials in a sweep cycle are capped by the MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP ratio."""
    state = Mock(spec=BeaconStateView)
    num_validator_withdrawals = 5
    num_pending_partials = 20  # More pending partials than can fit per cycle

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[Mock()] * num_pending_partials))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))
        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32)

    # ratio = MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP / (MAX_WITHDRAWALS_PER_PAYLOAD - MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP)
    #       = 8/(16-8) = 1.0
    # max_pending_in_cycle = ceil(5 * 1.0) = 5
    # actual_pending_in_cycle = min(20, 5) = 5
    # total = 5 + 5 = 10
    ratio = MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP / (
        MAX_WITHDRAWALS_PER_PAYLOAD - MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP
    )
    max_pending = math.ceil(num_validator_withdrawals * ratio)
    expected = num_validator_withdrawals + min(num_pending_partials, max_pending)
    assert result == expected


@pytest.mark.unit
def test_predict_withdrawals_empty_state(monkeypatch):
    """Empty state (no validators, no pending partials) produces zero withdrawals."""
    state = Mock(spec=BeaconStateView)

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[]))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[]))
        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32)

    assert result == 0


@pytest.mark.unit
def test_get_validators_withdrawals_empty():
    """Empty validator list produces no withdrawals."""
    state = BeaconStateViewFactory.build(
        slot=32,
        validators=[],
        balances=[],
        pending_partial_withdrawals=[],
        slashings=[],
    )
    result = get_validators_withdrawals(state, [], 32)
    assert result == []
