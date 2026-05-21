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
    SweepPrediction,
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
def test_get_sweep_delay_in_epochs(monkeypatch):
    state = Mock(spec=BeaconStateView)
    spec = Mock(spec=ChainConfig)
    spec.slots_per_epoch = 12
    predicted_withdrawals = 1000
    predicted = SweepPrediction(
        withdrawals_number=predicted_withdrawals, available_per_payload=MAX_WITHDRAWALS_PER_PAYLOAD
    )
    with monkeypatch.context() as m:
        m.setattr(sweep_module, "predict_withdrawals_number_in_sweep_cycle", Mock(return_value=predicted))
        result = get_sweep_delay_in_epochs(state, spec)

        expected_delay = math.ceil(predicted_withdrawals / MAX_WITHDRAWALS_PER_PAYLOAD / spec.slots_per_epoch) // 2
        assert result == expected_delay


@pytest.fixture()
def fake_beacon_state_view():
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
    result = get_pending_partial_withdrawals(fake_beacon_state_view)
    assert len(result) == 1
    assert result[0].validator_index == 1
    assert result[0].amount == 1


@pytest.mark.unit
def test_get_validators_withdrawals(fake_beacon_state_view):
    result = get_validators_withdrawals(
        fake_beacon_state_view,
        [
            Withdrawal(validator_index=1, amount=1),
            Withdrawal(validator_index=2, amount=1),
            Withdrawal(validator_index=2, amount=1),
        ],
        32,
    )
    assert len(result) == 1
    assert result[0].validator_index == 2
    assert result[0].amount == 10


@pytest.mark.unit
def test_only_validators_withdrawals():
    mock_state = BeaconStateViewFactory.build(
        slot=32,
        validators=ValidatorStateFactory.batch(2, effective_balance=32_000_000_000, withdrawable_epoch=0),
        balances=[32_000_000_000] * 2,
        pending_partial_withdrawals=[],
        slashings=[],
    )
    result = sweep_module.predict_withdrawals_number_in_sweep_cycle(mock_state, 32)
    assert result.withdrawals_number == 2


@pytest.mark.unit
def test_combined_withdrawals():
    mock_state = BeaconStateViewFactory.build(
        slot=32,
        validators=ValidatorStateFactory.batch(10, effective_balance=32_000_000_000, exit_epoch=123),
        balances=[32_000_000_001] * 10,
        pending_partial_withdrawals=[],
        slashings=[],
    )
    result = sweep_module.predict_withdrawals_number_in_sweep_cycle(mock_state, 32)
    assert result.withdrawals_number == 10


@pytest.mark.unit
def test_get_pending_partial_withdrawals__exiting_validator__returns_empty():
    """Validators with exit_epoch != FAR_FUTURE_EPOCH are excluded from pending partial withdrawals."""
    validator = LidoValidatorFactory.build(
        balance=Gwei(MIN_ACTIVATION_BALANCE + 100),
        validator=ValidatorStateFactory.build(
            effective_balance=MIN_ACTIVATION_BALANCE,
            exit_epoch=10,
        ),
    )
    state = BeaconStateViewFactory.build_with_validators(
        validators=[validator],
        pending_partial_withdrawals=[PendingPartialWithdrawal(validator_index=0, amount=100, withdrawable_epoch=1)],
        slashings=[],
        slot=32,
    )
    assert get_pending_partial_withdrawals(state) == []


@pytest.mark.unit
def test_get_pending_partial_withdrawals__low_effective_balance__returns_empty():
    """Validators with effective_balance < MIN_ACTIVATION_BALANCE are excluded."""
    validator = LidoValidatorFactory.build(
        balance=Gwei(MIN_ACTIVATION_BALANCE + 100),
        validator=ValidatorStateFactory.build(
            effective_balance=MIN_ACTIVATION_BALANCE - 1,
            exit_epoch=FAR_FUTURE_EPOCH,
        ),
    )
    state = BeaconStateViewFactory.build_with_validators(
        validators=[validator],
        pending_partial_withdrawals=[PendingPartialWithdrawal(validator_index=0, amount=100, withdrawable_epoch=1)],
        slashings=[],
        slot=32,
    )
    assert get_pending_partial_withdrawals(state) == []


@pytest.mark.unit
def test_get_pending_partial_withdrawals__no_excess_balance__returns_empty():
    """Validators with balance == MIN_ACTIVATION_BALANCE have no excess to withdraw."""
    validator = LidoValidatorFactory.build(
        balance=Gwei(MIN_ACTIVATION_BALANCE),
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
    assert get_pending_partial_withdrawals(state) == []


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__pending_partials_exceed_ratio__capped(monkeypatch):
    """Pending partials in a sweep cycle are capped by the MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP ratio."""
    state = Mock(spec=BeaconStateView)
    num_validator_withdrawals = 5
    num_pending_partials = 20

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[Mock()] * num_pending_partials))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))

        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32)

    # ratio = 8 / (16 - 8) = 1.0  →  max_pending = ceil(5 * 1.0) = 5
    ratio = MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP / (
        MAX_WITHDRAWALS_PER_PAYLOAD - MAX_PENDING_PARTIALS_PER_WITHDRAWALS_SWEEP
    )
    max_pending = math.ceil(num_validator_withdrawals * ratio)
    assert result.withdrawals_number == num_validator_withdrawals + min(num_pending_partials, max_pending)


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__empty_state__returns_zero(monkeypatch):
    """Empty state (no validators, no pending partials) produces zero withdrawals."""
    state = Mock(spec=BeaconStateView)

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[]))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[]))

        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32)

    assert result.withdrawals_number == 0


@pytest.mark.unit
def test_get_validators_withdrawals__empty_validators__returns_empty():
    """Empty validator list produces no withdrawals."""
    state = BeaconStateViewFactory.build(
        slot=32,
        validators=[],
        balances=[],
        pending_partial_withdrawals=[],
        slashings=[],
    )
    assert get_validators_withdrawals(state, [], 32) == []


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_builder_sweep_reduces_budget(monkeypatch):
    """Post-ePBS: builder sweep slots reduce available_for_validator_sweep."""
    state = Mock(spec=BeaconStateView)
    state.builder_pending_withdrawals = []
    num_validator_withdrawals = 10
    num_builder_sweep = 3  # builder sweep takes 3 of the 15 remaining slots

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[]))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))
        m.setattr(sweep_module, "get_builders_sweep_withdrawals", Mock(return_value=[Mock()] * num_builder_sweep))

        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32, is_epbs_active=True)

    # builder_pending=0, partials=0, builder_sweep=3
    # available_for_validator_sweep = 16 - 0 - 0 - 3 = 13
    # partial_slots = min(0, 8) = 0
    # available_per_payload = 13 + 0 = 13
    expected_available_for_validator = MAX_WITHDRAWALS_PER_PAYLOAD - 0 - 0 - num_builder_sweep
    expected_available_per_payload = expected_available_for_validator + 0  # partial_slots=0
    assert result.available_per_payload == expected_available_per_payload
    assert result.withdrawals_number == num_validator_withdrawals


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_with_partials(monkeypatch):
    """Post-ePBS: partial_slots (not actual_partial_cap) is added to available_per_payload."""
    state = Mock(spec=BeaconStateView)
    state.builder_pending_withdrawals = []
    num_validator_withdrawals = 10
    num_pending_partials = 5  # fewer than actual_partial_cap=8

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[Mock()] * num_pending_partials))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))
        m.setattr(sweep_module, "get_builders_sweep_withdrawals", Mock(return_value=[]))

        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32, is_epbs_active=True)

    # builder_pending=0, partials=5, builder_sweep=0
    # actual_partial_cap = min(8, 15) = 8
    # partial_slots = min(5, 8) = 5
    # available_for_validator_sweep = 16 - 0 - 5 - 0 = 11
    # available_per_payload = 11 + 5 = 16
    assert result.available_per_payload == 16
    assert result.withdrawals_number == num_validator_withdrawals + num_pending_partials


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_builder_pending_reduces_partial_cap(monkeypatch):
    """Post-ePBS: builder_pending reduces actual_partial_cap, leaving fewer slots for partials."""
    state = Mock(spec=BeaconStateView)
    state.builder_pending_withdrawals = [Mock()] * 10  # consumes 10 of 15 slots
    num_validator_withdrawals = 10
    num_pending_partials = 8  # more than the reduced cap

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[Mock()] * num_pending_partials))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))
        m.setattr(sweep_module, "get_builders_sweep_withdrawals", Mock(return_value=[]))

        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32, is_epbs_active=True)

    # builder_pending=10, actual_partial_cap = min(8, 15-10) = 5
    # partial_slots = min(8, 5) = 5
    # available_for_validator_sweep = 16 - 10 - 5 - 0 = 1
    # available_per_payload = 1 + 5 = 6
    assert result.available_per_payload == 6


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_builder_pending_reduces_budget(monkeypatch):
    """Post-ePBS: large builder_pending queue reduces partial cap and validator sweep slots."""
    state = Mock(spec=BeaconStateView)
    # builder_pending fills 15 slots → actual_partial_cap = 0, builder_sweep = 0, validator = 1
    state.builder_pending_withdrawals = [Mock()] * 100
    num_validator_withdrawals = 10

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_pending_partial_withdrawals", Mock(return_value=[]))
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))
        m.setattr(sweep_module, "get_builders_sweep_withdrawals", Mock(return_value=[]))

        result = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32, is_epbs_active=True)

    # builder_pending_per_block = min(100, 15) = 15
    # actual_partial_cap = min(8, 15-15) = 0
    # builder_sweep prior_count = 15 + 0 = 15 → returns [] (limit reached)
    # available_for_validator_sweep = 16 - 15 - 0 - 0 = 1
    # available_per_payload = 1 + 0 = 1
    assert result.available_per_payload == 1
    assert result.withdrawals_number == num_validator_withdrawals  # ratio=0 → no partials added
