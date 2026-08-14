from typing import cast
from unittest.mock import Mock

import pytest

import src.modules.oracles.ejector.sweep as sweep_module
from src.constants import MAX_SEED_LOOKAHEAD
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.ejector import Ejector
from src.modules.oracles.ejector.sweep import get_sweep_delay_in_epochs, predict_withdrawals_number_in_sweep_cycle
from src.providers.consensus.types import BeaconSpecResponse, BeaconStateView
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.validator_state import (
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    get_exit_churn_limit,
)
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import BeaconSpecResponseFactory, ChainConfigFactory


ETH = 10**9  # Gwei
FORTY_MILLION_ETH = Gwei(40_000_000 * ETH)

# /eth/v1/config/spec values, not oracle constants — see BeaconSpecResponse.gloas_exit_churn_params.
MAINNET_CHURN_PARAMS = (Gwei(128 * ETH), 2**15)
MINIMAL_CHURN_PARAMS = (Gwei(64 * ETH), 2**4)


@pytest.mark.unit
class TestExitChurnLimitEip8061:
    @pytest.mark.parametrize(
        ("total_active_balance", "params", "expected"),
        [
            # Mainnet preset. 40M ETH // 2**15 = 1220.703125 ETH -> floored to the increment.
            pytest.param(FORTY_MILLION_ETH, MAINNET_CHURN_PARAMS, Gwei(1220 * ETH), id="mainnet-rounds-down"),
            # Exact multiple of the quotient: nothing to floor off.
            pytest.param(Gwei(1220 * ETH * 2**15), MAINNET_CHURN_PARAMS, Gwei(1220 * ETH), id="mainnet-exact"),
            # Exactly at the floor: quotient term equals MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA.
            pytest.param(Gwei(128 * ETH * 2**15), MAINNET_CHURN_PARAMS, Gwei(128 * ETH), id="mainnet-at-floor"),
            # One Gwei below the floor boundary: the floor wins.
            pytest.param(Gwei(128 * ETH * 2**15 - 1), MAINNET_CHURN_PARAMS, Gwei(128 * ETH), id="mainnet-below-floor"),
            # Minimal preset: same stake, a very different limit — the parameters are not interchangeable.
            pytest.param(FORTY_MILLION_ETH, MINIMAL_CHURN_PARAMS, Gwei(2_500_000 * ETH), id="minimal-exact"),
            # 1048 ETH // 2**4 = 65.5 ETH -> floored to 65 ETH.
            pytest.param(Gwei(1048 * ETH), MINIMAL_CHURN_PARAMS, Gwei(65 * ETH), id="minimal-rounds-down"),
            # Below the minimal floor of 64 ETH: 1000 ETH // 2**4 = 62.5 ETH.
            pytest.param(Gwei(1000 * ETH), MINIMAL_CHURN_PARAMS, Gwei(64 * ETH), id="minimal-below-floor"),
        ],
    )
    def test_get_exit_churn_limit__preset_vectors__match_spec_formula(self, total_active_balance, params, expected):
        assert get_exit_churn_limit(total_active_balance, *params) == expected

    def test_get_exit_churn_limit__uncapped_is_about_5x_activation_limit(self):
        # The pre-fork activation/exit churn is capped (256 ETH/epoch); EIP-8061 removes the cap.
        exit_churn = get_exit_churn_limit(FORTY_MILLION_ETH, *MAINNET_CHURN_PARAMS)
        activation_churn = get_activation_exit_churn_limit(FORTY_MILLION_ETH)
        assert activation_churn == Gwei(256 * ETH)
        assert 4.5 < exit_churn / activation_churn < 5.0


@pytest.mark.unit
class TestGloasChurnParamsFromConfigSpec:
    @staticmethod
    def _spec(**overrides) -> BeaconSpecResponse:
        # String values mirror the real /eth/v1/config/spec response shape.
        return BeaconSpecResponse.from_response(
            DEPOSIT_CHAIN_ID="1",
            SLOTS_PER_EPOCH="32",
            DEPOSIT_CONTRACT_ADDRESS="0x00",
            SLOTS_PER_HISTORICAL_ROOT="8192",
            SECONDS_PER_SLOT="12",
            **overrides,
        )

    def test_gloas_exit_churn_params__announced_by_node__returns_coerced_values(self):
        # Arrange: the values a Glamsterdam devnet node announces, as strings.
        spec = self._spec(MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA="128000000000", CHURN_LIMIT_QUOTIENT_GLOAS="32768")

        # Act / Assert
        assert spec.gloas_exit_churn_params() == (128 * ETH, 2**15)

    @pytest.mark.parametrize(
        ("overrides", "missing"),
        [
            ({"CHURN_LIMIT_QUOTIENT_GLOAS": "32768"}, "MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA"),
            ({"MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA": "128000000000"}, "CHURN_LIMIT_QUOTIENT_GLOAS"),
        ],
    )
    def test_gloas_exit_churn_params__param_not_announced__raises(self, overrides, missing):
        spec = self._spec(**overrides)

        with pytest.raises(BeaconSpecResponse.MissingGloasChurnParams, match=missing):
            spec.gloas_exit_churn_params()


@pytest.mark.unit
class TestEjectorChurnUsesConfigSpec:
    """The projected exit epoch must follow the node's churn parameters, not compiled-in values."""

    EXITING_BALANCE = Gwei(5_000 * ETH)

    @pytest.fixture
    def ejector(self, web3: Web3) -> Ejector:
        web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(return_value=1)
        ejector = Ejector(web3)
        ejector.get_chain_config = Mock(return_value=cast(ChainConfig, ChainConfigFactory.build()))
        ejector._get_total_active_balance = Mock(return_value=FORTY_MILLION_ETH)
        return ejector

    @staticmethod
    def _exit_epoch(ejector: Ejector, spec: BeaconSpecResponse) -> EpochNumber:
        blockstamp = ReferenceBlockStampFactory.build(
            ref_epoch=EpochNumber(1000), ref_slot=SlotNumber(32_000), slot_number=SlotNumber(32_000)
        )
        ejector.w3.cc = Mock()
        ejector.w3.cc.get_config_spec = Mock(return_value=spec)
        ejector.w3.cc.is_gloas_epoch = Mock(side_effect=lambda epoch: epoch >= spec.GLOAS_FORK_EPOCH)
        state = BeaconStateView(
            slot=blockstamp.slot_number,
            validators=[],
            balances=[],
            earliest_exit_epoch=blockstamp.ref_epoch,
            exit_balance_to_consume=Gwei(0),
            slashings=[],
        )
        return ejector.compute_exit_epoch_and_update_churn(
            state, TestEjectorChurnUsesConfigSpec.EXITING_BALANCE, blockstamp
        )

    def test_compute_exit_epoch__mainnet_params__queues_behind_the_1220_eth_churn(self, ejector: Ejector):
        # Arrange: 1220 ETH/epoch of churn, so a 5000 ETH exit spills over 4 further epochs.
        spec = BeaconSpecResponseFactory.build(GLOAS_FORK_EPOCH=0)

        # Act
        exit_epoch = self._exit_epoch(ejector, spec)

        # Assert
        assert exit_epoch == 1000 + (1 + MAX_SEED_LOOKAHEAD) + 4

    def test_compute_exit_epoch__minimal_params__fits_in_the_first_epoch(self, ejector: Ejector):
        # Arrange: the minimal preset churns 2.5M ETH/epoch, so the same exit spills over nothing.
        # A compiled-in mainnet quotient would push this out by 4 epochs.
        min_per_epoch_churn, quotient = MINIMAL_CHURN_PARAMS
        spec = BeaconSpecResponseFactory.build(
            GLOAS_FORK_EPOCH=0,
            MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA=min_per_epoch_churn,
            CHURN_LIMIT_QUOTIENT_GLOAS=quotient,
        )

        # Act
        exit_epoch = self._exit_epoch(ejector, spec)

        # Assert
        assert exit_epoch == 1000 + (1 + MAX_SEED_LOOKAHEAD)

    def test_compute_exit_epoch__gloas_active_but_params_not_announced__raises(self, ejector: Ejector):
        # Arrange: a node that activates Gloas without announcing the churn parameters.
        spec = BeaconSpecResponseFactory.build(
            GLOAS_FORK_EPOCH=0, MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA=0, CHURN_LIMIT_QUOTIENT_GLOAS=0
        )

        # Act / Assert: refuse to project the exit queue with guessed parameters.
        with pytest.raises(BeaconSpecResponse.MissingGloasChurnParams):
            self._exit_epoch(ejector, spec)


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
        ejector.w3.cc.get_config_spec = Mock(
            return_value=BeaconSpecResponseFactory.build(
                GLOAS_FORK_EPOCH=2,
                MIN_PER_EPOCH_CHURN_LIMIT_ELECTRA=MAINNET_CHURN_PARAMS[0],
                CHURN_LIMIT_QUOTIENT_GLOAS=MAINNET_CHURN_PARAMS[1],
            )
        )
        ejector._get_total_active_balance = Mock(return_value=FORTY_MILLION_ETH)
        blockstamp = self._blockstamp_with_child_anchor()
        state = Mock(earliest_exit_epoch=EpochNumber(0), exit_balance_to_consume=Gwei(0))
        # One uncapped churn: fits a single epoch post-fork, spills over ~5 epochs pre-fork.
        exit_balance = get_exit_churn_limit(FORTY_MILLION_ETH, *MAINNET_CHURN_PARAMS)

        # Act
        result = ejector.compute_exit_epoch_and_update_churn(state, exit_balance, blockstamp)

        # Assert
        assert result == compute_activation_exit_epoch(blockstamp.ref_epoch)
        assert ejector.w3.cc.is_gloas_epoch.call_args.args[0] == EpochNumber(2)
