"""Unit tests for the EIP-8061 exit churn limit and the EIP-7732 sweep-delay adjustment."""

from unittest.mock import Mock

import pytest

import src.modules.oracles.ejector.sweep as sweep_module
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.sweep import get_sweep_delay_in_epochs, predict_withdrawals_number_in_sweep_cycle
from src.types import Gwei
from src.utils.validator_state import get_activation_exit_churn_limit, get_exit_churn_limit


ETH = 10**9  # Gwei
FORTY_MILLION_ETH = Gwei(40_000_000 * ETH)


@pytest.mark.unit
class TestExitChurnLimitEip8061:
    def test_get_exit_churn_limit__at_40m_eth__is_about_1220_eth(self):
        # ~40M ETH total active stake -> ~1220 ETH/epoch (uncapped, halved quotient).
        assert get_exit_churn_limit(FORTY_MILLION_ETH) == Gwei(1220 * ETH)

    def test_get_exit_churn_limit__uncapped_is_about_5x_activation_limit(self):
        # The pre-fork activation/exit churn is capped (256 ETH/epoch); EIP-8061 removes the cap.
        exit_churn = get_exit_churn_limit(FORTY_MILLION_ETH)
        activation_churn = get_activation_exit_churn_limit(FORTY_MILLION_ETH)
        assert activation_churn == Gwei(256 * ETH)
        assert 4.5 < exit_churn / activation_churn < 5.0

    def test_get_exit_churn_limit__is_multiple_of_effective_balance_increment(self):
        assert get_exit_churn_limit(FORTY_MILLION_ETH) % ETH == 0


@pytest.mark.unit
class TestSweepDelayGloas:
    def test_predict_withdrawals__gloas__excludes_pending_partials(self, monkeypatch):
        # Arrange
        state = Mock()
        validators_withdrawals = [object(), object(), object()]
        get_validators = Mock(return_value=validators_withdrawals)
        get_partials = Mock(return_value=[object(), object()])
        monkeypatch.setattr(sweep_module, "get_validators_withdrawals", get_validators)
        monkeypatch.setattr(sweep_module, "get_pending_partial_withdrawals", get_partials)

        # Act
        result = predict_withdrawals_number_in_sweep_cycle(state, slots_per_epoch=32, is_gloas_active=True)

        # Assert: only validator withdrawals counted; partials are neither fetched nor passed in.
        assert result == len(validators_withdrawals)
        get_partials.assert_not_called()
        assert get_validators.call_args.args[1] == []

    def test_predict_withdrawals__pre_gloas__includes_pending_partials(self, monkeypatch):
        # Arrange
        state = Mock()
        monkeypatch.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[object()]))
        get_partials = Mock(return_value=[])
        monkeypatch.setattr(sweep_module, "get_pending_partial_withdrawals", get_partials)

        # Act
        predict_withdrawals_number_in_sweep_cycle(state, slots_per_epoch=32, is_gloas_active=False)

        # Assert: legacy path still consults the partials queue.
        get_partials.assert_called_once()

    def test_get_sweep_delay_in_epochs__passes_is_gloas_through(self, monkeypatch):
        # Arrange
        spec = Mock(spec=ChainConfig)
        spec.slots_per_epoch = 32
        predict = Mock(return_value=100)
        monkeypatch.setattr(sweep_module, "predict_withdrawals_number_in_sweep_cycle", predict)

        # Act
        get_sweep_delay_in_epochs(Mock(), spec, is_gloas_active=True)

        # Assert
        assert predict.call_args.args[2] is True
