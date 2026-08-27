from typing import cast
from unittest.mock import Mock

import pytest

import src.modules.oracles.ejector.sweep as sweep_module
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.ejector import Ejector
from src.modules.oracles.ejector.sweep import get_sweep_delay_in_epochs, predict_withdrawals_number_in_sweep_cycle
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.validator_state import (
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    get_exit_churn_limit,
)
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory


ETH = 10**9  # Gwei
FORTY_MILLION_ETH = Gwei(40_000_000 * ETH)


@pytest.mark.unit
class TestExitChurnLimitEip8061:
    def test_get_exit_churn_limit__at_40m_eth__is_about_1220_eth(self):
        assert get_exit_churn_limit(FORTY_MILLION_ETH) == Gwei(1220 * ETH)

    def test_get_exit_churn_limit__uncapped_is_about_5x_activation_limit(self):
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

        # Assert
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

        # Assert
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


@pytest.mark.unit
class TestForkGateEpoch:
    """Under EIP-7732 the anchor block is ref_slot's child, so its epoch can differ from ref_epoch."""

    @pytest.fixture
    def ejector(self, web3: Web3) -> Ejector:
        web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(return_value=1)
        instance = Ejector(web3)
        instance.get_chain_config = Mock(return_value=cast(ChainConfig, ChainConfigFactory.build()))
        return instance

    @staticmethod
    def _blockstamp_with_child_anchor() -> ReferenceBlockStamp:
        """ref_slot is the last slot of epoch 1; its data lives in the first block of epoch 2."""
        return cast(
            ReferenceBlockStamp,
            ReferenceBlockStampFactory.build(
                ref_slot=SlotNumber(63),
                ref_epoch=EpochNumber(1),
                slot_number=SlotNumber(64),
            ),
        )

    def test_state_epoch__anchor_in_next_epoch__follows_slot_number(self, ejector: Ejector):
        # Act
        result = ejector._state_epoch(self._blockstamp_with_child_anchor())

        # Assert
        assert result == EpochNumber(2)

    def test_compute_exit_epoch_and_update_churn__fork_active_at_anchor__uses_uncapped_churn(self, ejector: Ejector):
        # Arrange: the fork starts at epoch 2 — active at the anchor block, not yet at ref_epoch.
        ejector.w3.cc.is_gloas_epoch = Mock(side_effect=lambda epoch: epoch >= 2)
        ejector._get_total_active_balance = Mock(return_value=FORTY_MILLION_ETH)
        blockstamp = self._blockstamp_with_child_anchor()
        state = Mock(earliest_exit_epoch=EpochNumber(0), exit_balance_to_consume=Gwei(0))
        # One uncapped churn: fits a single epoch post-fork, spills over ~5 epochs pre-fork.
        exit_balance = get_exit_churn_limit(FORTY_MILLION_ETH)

        # Act
        result = ejector.compute_exit_epoch_and_update_churn(state, exit_balance, blockstamp)

        # Assert
        assert result == compute_activation_exit_epoch(blockstamp.ref_epoch)
        assert ejector.w3.cc.is_gloas_epoch.call_args.args[0] == EpochNumber(2)
