from typing import cast
from unittest.mock import Mock

import pytest

import src.modules.oracles.ejector.sweep as sweep_module
from src.constants import (
    COMPOUNDING_WITHDRAWAL_PREFIX,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MIN_ACTIVATION_BALANCE,
)
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.ejector import Ejector
from src.modules.oracles.ejector.sweep import get_sweep_delay_in_epochs, predict_withdrawals_number_in_sweep_cycle
from src.providers.consensus.types import PendingPartialWithdrawal
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.validator_state import (
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    get_exit_churn_limit,
)
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import ValidatorStateFactory


ETH = 10**9  # Gwei
FORTY_MILLION_ETH = Gwei(40_000_000 * ETH)


@pytest.mark.unit
class TestExitChurnLimitEip8061:
    def test_get_exit_churn_limit__at_40m_eth__is_about_1220_eth(self):
        assert get_exit_churn_limit(FORTY_MILLION_ETH) == Gwei(1220 * ETH)

    def test_get_exit_churn_limit__at_40m_eth__is_about_5x_activation_limit(self):
        exit_churn = get_exit_churn_limit(FORTY_MILLION_ETH)
        activation_churn = get_activation_exit_churn_limit(FORTY_MILLION_ETH)
        assert activation_churn == Gwei(256 * ETH)
        assert 4.5 < exit_churn / activation_churn < 5.0

    def test_get_exit_churn_limit__at_40m_eth__is_multiple_of_effective_balance_increment(self):
        assert get_exit_churn_limit(FORTY_MILLION_ETH) % ETH == 0


@pytest.mark.unit
class TestSweepDelayGloas:
    @staticmethod
    def _state_with_partials_draining_capped_validators():
        """Four compounding validators sit 1 ETH above the cap with a queued 100 ETH partial each, so once
        the partials are applied the ordinary sweep has nothing to skim from them. Two 0x01 validators stay
        skimmable."""
        capped = ValidatorStateFactory.batch(
            4,
            withdrawal_credentials=COMPOUNDING_WITHDRAWAL_PREFIX + '00' * 30,
            effective_balance=MAX_EFFECTIVE_BALANCE_ELECTRA,
            withdrawable_epoch=FAR_FUTURE_EPOCH,
        )
        ordinary = ValidatorStateFactory.batch(
            2,
            withdrawal_credentials=ETH1_ADDRESS_WITHDRAWAL_PREFIX + '00' * 31,
            effective_balance=MIN_ACTIVATION_BALANCE,
            withdrawable_epoch=FAR_FUTURE_EPOCH,
        )
        return BeaconStateViewFactory.build(
            slot=32,
            validators=capped + ordinary,
            balances=[MAX_EFFECTIVE_BALANCE_ELECTRA + ETH] * 4 + [MIN_ACTIVATION_BALANCE + ETH] * 2,
            pending_partial_withdrawals=[
                PendingPartialWithdrawal(validator_index=i, amount=100 * ETH, withdrawable_epoch=0) for i in range(4)
            ],
            slashings=[],
        )

    def test_predict_withdrawals_number_in_sweep_cycle__gloas__partials_drain_capped_validators__skim_not_counted(
        self,
    ):
        # Arrange
        state = self._state_with_partials_draining_capped_validators()

        # Act
        result = predict_withdrawals_number_in_sweep_cycle(state, slots_per_epoch=32, is_gloas_active=True)

        # Assert — only the two 0x01 validators; partial entries themselves are not counted
        assert result == 2

    def test_predict_withdrawals_number_in_sweep_cycle__gloas__never_exceeds_pre_gloas(self):
        # Arrange
        state = self._state_with_partials_draining_capped_validators()

        # Act
        gloas = predict_withdrawals_number_in_sweep_cycle(state, slots_per_epoch=32, is_gloas_active=True)
        pre_gloas = predict_withdrawals_number_in_sweep_cycle(state, slots_per_epoch=32, is_gloas_active=False)

        # Assert
        assert gloas <= pre_gloas

    def test_predict_withdrawals_number_in_sweep_cycle__pre_gloas__includes_pending_partials(self, monkeypatch):
        # Arrange
        state = Mock()
        monkeypatch.setattr(sweep_module, "get_validators_withdrawals", Mock(return_value=[object()]))
        get_partials = Mock(return_value=[])
        monkeypatch.setattr(sweep_module, "get_pending_partial_withdrawals", get_partials)

        # Act
        predict_withdrawals_number_in_sweep_cycle(state, slots_per_epoch=32, is_gloas_active=False)

        # Assert
        get_partials.assert_called_once()

    def test_get_sweep_delay_in_epochs__gloas_active__passes_flag_through(self, monkeypatch):
        # Arrange
        predict = Mock(return_value=100)
        monkeypatch.setattr(sweep_module, "predict_withdrawals_number_in_sweep_cycle", predict)

        # Act
        get_sweep_delay_in_epochs(Mock(), 32, is_gloas_active=True)

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
                epoch_number=EpochNumber(2),
            ),
        )

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
        ejector.w3.cc.is_gloas_epoch.assert_called_once_with(EpochNumber(2))

    def test_compute_exit_epoch_and_update_churn__called_per_candidate__reads_fork_config_once(self, ejector: Ejector):
        # Arrange
        ejector.w3.cc.is_gloas_epoch = Mock(return_value=True)
        ejector._get_total_active_balance = Mock(return_value=FORTY_MILLION_ETH)
        blockstamp = self._blockstamp_with_child_anchor()
        state = Mock(earliest_exit_epoch=EpochNumber(0), exit_balance_to_consume=Gwei(0))

        # Act
        for exit_balance in (Gwei(32 * ETH), Gwei(64 * ETH), Gwei(96 * ETH)):
            ejector.compute_exit_epoch_and_update_churn(state, exit_balance, blockstamp)

        # Assert
        ejector.w3.cc.is_gloas_epoch.assert_called_once_with(EpochNumber(2))
