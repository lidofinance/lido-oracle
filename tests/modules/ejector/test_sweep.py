import math
from unittest.mock import Mock

import pytest

import src.modules.oracles.ejector.sweep as sweep_module
from src.constants import (
    MAX_WITHDRAWALS_PER_PAYLOAD,
    MIN_ACTIVATION_BALANCE,
)
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.sweep import (
    get_sweep_delay_in_epochs,
    get_validators_withdrawals,
)
from src.providers.consensus.types import BeaconStateView
from src.types import Gwei
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


@pytest.mark.unit
def test_get_sweep_delay_in_epochs(monkeypatch):
    state = Mock(spec=BeaconStateView)
    spec = Mock(spec=ChainConfig)
    spec.slots_per_epoch = 12
    predicted_withdrawals = 1000
    with monkeypatch.context() as m:
        m.setattr(
            sweep_module,
            "predict_withdrawals_number_in_sweep_cycle",
            Mock(return_value=(predicted_withdrawals, MAX_WITHDRAWALS_PER_PAYLOAD)),
        )
        result = get_sweep_delay_in_epochs(state, spec)

        expected_delay = math.ceil(predicted_withdrawals / MAX_WITHDRAWALS_PER_PAYLOAD / spec.slots_per_epoch) // 2
        assert result == expected_delay


@pytest.mark.unit
def test_get_validators_withdrawals():
    validators = [
        LidoValidatorFactory.build_with_balance(Gwei(1000)),
        LidoValidatorFactory.build_with_balance(Gwei(MIN_ACTIVATION_BALANCE + 1)),
        LidoValidatorFactory.build_with_balance(Gwei(MIN_ACTIVATION_BALANCE + 12)),
    ]
    min_withdraw_epoch = min([v.validator.withdrawable_epoch for v in validators])
    min_withdraw_slot = min_withdraw_epoch * 12 - 10
    state = BeaconStateViewFactory.build_with_validators(
        validators=validators,
        pending_partial_withdrawals=[],
        slashings=[],
        slot=min_withdraw_slot,
    )
    result = get_validators_withdrawals(state, 12)
    assert len(result) == 2
    assert result[0].validator_index == 1
    assert result[0].amount == 1
    assert result[1].validator_index == 2
    assert result[1].amount == 12


@pytest.mark.unit
def test_only_validators_withdrawals():
    mock_state = BeaconStateViewFactory.build(
        slot=32,
        validators=ValidatorStateFactory.batch(2, effective_balance=32_000_000_000, withdrawable_epoch=0),
        balances=[32_000_000_000] * 2,
        pending_partial_withdrawals=[],
        slashings=[],
    )
    withdrawals_number, _ = sweep_module.predict_withdrawals_number_in_sweep_cycle(mock_state, 32)
    assert withdrawals_number == 2


@pytest.mark.unit
def test_combined_withdrawals():
    mock_state = BeaconStateViewFactory.build(
        slot=32,
        validators=ValidatorStateFactory.batch(10, effective_balance=32_000_000_000, exit_epoch=123),
        balances=[32_000_000_001] * 10,
        pending_partial_withdrawals=[],
        slashings=[],
    )
    withdrawals_number, _ = sweep_module.predict_withdrawals_number_in_sweep_cycle(mock_state, 32)
    assert withdrawals_number == 10


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__empty_state__returns_zero(monkeypatch):
    """Empty state (no validators) produces zero withdrawals."""
    state = Mock(spec=BeaconStateView)

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[]))

        withdrawals_number, _ = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32)

    assert withdrawals_number == 0


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
    assert get_validators_withdrawals(state, 32) == []


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__available_per_payload_is_max(monkeypatch):
    """Pre-ePBS: available_per_payload is MAX_WITHDRAWALS_PER_PAYLOAD."""
    state = Mock(spec=BeaconStateView)
    num_validator_withdrawals = 10

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))

        withdrawals_number, available_per_payload = sweep_module.predict_withdrawals_number_in_sweep_cycle(state, 32)

    assert available_per_payload == MAX_WITHDRAWALS_PER_PAYLOAD
    assert withdrawals_number == num_validator_withdrawals


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_no_builder_pending(monkeypatch):
    """Post-ePBS: no builder_pending → available_per_payload = MAX_WITHDRAWALS_PER_PAYLOAD."""
    state = Mock(spec=BeaconStateView)
    state.builder_pending_withdrawals = []
    num_validator_withdrawals = 10

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))

        withdrawals_number, available_per_payload = sweep_module.predict_withdrawals_number_in_sweep_cycle(
            state, 32, is_epbs_active=True
        )

    assert available_per_payload == MAX_WITHDRAWALS_PER_PAYLOAD
    assert withdrawals_number == num_validator_withdrawals


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_builder_pending_reduces_available(monkeypatch):
    """Post-ePBS: builder_pending reduces available_per_payload; partial cap is not subtracted."""
    state = Mock(spec=BeaconStateView)
    state.builder_pending_withdrawals = [Mock()] * 3
    num_validator_withdrawals = 10

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))

        withdrawals_number, available_per_payload = sweep_module.predict_withdrawals_number_in_sweep_cycle(
            state, 32, is_epbs_active=True
        )

    # builder_pending_per_block = min(3, 15) = 3 → available = 16 - 3 = 13
    assert available_per_payload == MAX_WITHDRAWALS_PER_PAYLOAD - 3
    assert withdrawals_number == num_validator_withdrawals


@pytest.mark.unit
def test_predict_withdrawals_number_in_sweep_cycle__epbs_builder_pending_saturated(monkeypatch):
    """Post-ePBS: builder_pending capped at MAX_WITHDRAWALS_PER_PAYLOAD - 1 → available = 1."""
    state = Mock(spec=BeaconStateView)
    state.builder_pending_withdrawals = [Mock()] * 100
    num_validator_withdrawals = 10

    with monkeypatch.context() as m:
        m.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[Mock()] * num_validator_withdrawals))

        withdrawals_number, available_per_payload = sweep_module.predict_withdrawals_number_in_sweep_cycle(
            state, 32, is_epbs_active=True
        )

    # builder_pending_per_block = min(100, 15) = 15 → available = 16 - 15 = 1
    assert available_per_payload == 1
    assert withdrawals_number == num_validator_withdrawals
