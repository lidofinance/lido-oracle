from unittest.mock import Mock

import pytest
from web3.types import Wei

from src.constants import COMPOUNDING_WITHDRAWAL_PREFIX, FAR_FUTURE_EPOCH
from src.modules.oracles.accounting.types import ReportSimulationFeeDistribution, ReportSimulationResults
from src.services.bunker import BunkerService
from src.types import EpochNumber, Gwei, ReferenceBlockStamp
from src.web3py.extensions.lido_validators import LidoValidator
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.contract_responses import ReportSimulationResultsFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorFactory, ValidatorStateFactory


@pytest.fixture
def bunker(web3) -> BunkerService:
    return BunkerService(web3)


@pytest.fixture
def blockstamp() -> ReferenceBlockStamp:
    return ReferenceBlockStampFactory.build(ref_epoch=EpochNumber(100))


def make_lido_validator(
    effective_balance: int,
    *,
    slashed: bool = False,
    activation_epoch: int = 0,
    exit_epoch: int = FAR_FUTURE_EPOCH,
    withdrawable_epoch: int = FAR_FUTURE_EPOCH,
) -> LidoValidator:
    return LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(
            withdrawal_credentials=COMPOUNDING_WITHDRAWAL_PREFIX,
            effective_balance=Gwei(effective_balance),
            slashed=slashed,
            activation_epoch=EpochNumber(activation_epoch),
            exit_epoch=EpochNumber(exit_epoch),
            withdrawable_epoch=EpochNumber(withdrawable_epoch),
        )
    )


def make_network_validator(effective_balance: int, *, exit_epoch: int = FAR_FUTURE_EPOCH):
    return ValidatorFactory.build(
        validator=ValidatorStateFactory.build(
            withdrawal_credentials=COMPOUNDING_WITHDRAWAL_PREFIX,
            effective_balance=Gwei(effective_balance),
            slashed=False,
            activation_epoch=EpochNumber(0),
            exit_epoch=EpochNumber(exit_epoch),
            withdrawable_epoch=EpochNumber(FAR_FUTURE_EPOCH),
        )
    )


def configure_slashing_impact(bunker: BunkerService, base_rate_ppm: int, threshold_ppm: int) -> None:
    config = bunker.w3.lido_contracts.oracle_daemon_config
    config.bunker_base_slashing_impact_rate_ppm = Mock(return_value=base_rate_ppm)
    config.bunker_slashing_impact_threshold_ppm = Mock(return_value=threshold_ppm)


class TestIsBunkerMode:
    @pytest.mark.unit
    def test_is_bunker_mode__before_first_report__returns_turbo(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
    ) -> None:
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=0)

        result = bunker.is_bunker_mode(blockstamp, ReportSimulationResultsFactory.build())

        assert result is False
        bunker.w3.cc.get_state_view.assert_not_called()

    @pytest.mark.unit
    def test_is_bunker_mode__negative_cl_rebase__returns_bunker(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
    ) -> None:
        state = BeaconStateViewFactory.build_with_validators([], slashings=[])
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=1)
        bunker.w3.cc.get_state_view = Mock(return_value=state)
        bunker.w3.lido_validators.get_active_lido_validators = Mock(return_value=[])
        bunker.is_negative_cl_rebase = Mock(return_value=True)
        bunker.is_slashing_impact_big_enough = Mock()

        result = bunker.is_bunker_mode(blockstamp, ReportSimulationResultsFactory.build())

        assert result is True
        bunker.is_slashing_impact_big_enough.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.parametrize(('is_slashing_impact_big_enough', 'expected'), [(True, True), (False, False)])
    def test_is_bunker_mode__non_negative_cl_rebase__uses_slashing_impact(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
        is_slashing_impact_big_enough: bool,
        expected: bool,
    ) -> None:
        state = BeaconStateViewFactory.build_with_validators(
            [make_network_validator(32 * 10**9)],
            slashings=[Gwei(7 * 10**9)],
        )
        all_validators = state.indexed_validators
        lido_validators = [make_lido_validator(32 * 10**9)]
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=1)
        bunker.w3.cc.get_state_view = Mock(return_value=state)
        bunker.w3.lido_validators.get_active_lido_validators = Mock(return_value=lido_validators)
        bunker.is_negative_cl_rebase = Mock(return_value=False)
        bunker.is_slashing_impact_big_enough = Mock(return_value=is_slashing_impact_big_enough)

        result = bunker.is_bunker_mode(blockstamp, ReportSimulationResultsFactory.build())

        assert result is expected
        bunker.is_slashing_impact_big_enough.assert_called_once_with(
            blockstamp,
            all_validators,
            lido_validators,
            state.slashings,
        )


class TestSlashingImpact:
    @pytest.mark.unit
    def test_is_slashing_impact_big_enough__zero_lido_exposure__returns_false(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
    ) -> None:
        not_activated = make_lido_validator(32 * 10**9, slashed=True, activation_epoch=blockstamp.ref_epoch + 1)

        result = bunker.is_slashing_impact_big_enough(blockstamp, [], [not_activated], [])

        assert result is False
        bunker.w3.lido_contracts.oracle_daemon_config.bunker_base_slashing_impact_rate_ppm.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ('lido_exposure_balance', 'expected'),
        [
            (125 * 10**9, True),
            (126 * 10**9, False),
        ],
    )
    def test_is_slashing_impact_big_enough__near_threshold__uses_single_rounding(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
        lido_exposure_balance: int,
        expected: bool,
    ) -> None:
        lido_validators = [
            make_lido_validator(1 * 10**9, slashed=True),
            make_lido_validator(lido_exposure_balance - 1 * 10**9),
        ]
        network_validators = [make_network_validator(lido_exposure_balance)]
        configure_slashing_impact(bunker, base_rate_ppm=5_000, threshold_ppm=40)

        result = bunker.is_slashing_impact_big_enough(
            blockstamp,
            network_validators,
            lido_validators,
            [],
        )

        assert result is expected
        config = bunker.w3.lido_contracts.oracle_daemon_config
        config.bunker_base_slashing_impact_rate_ppm.assert_called_once_with(blockstamp.block_hash)
        config.bunker_slashing_impact_threshold_ppm.assert_called_once_with(blockstamp.block_hash)

    @pytest.mark.unit
    def test_is_slashing_impact_big_enough__network_only_slashing__returns_false(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
    ) -> None:
        lido_validators = [make_lido_validator(100 * 10**9)]
        network_validators = [make_network_validator(1_000 * 10**9)]
        configure_slashing_impact(bunker, base_rate_ppm=5_000, threshold_ppm=1)

        result = bunker.is_slashing_impact_big_enough(
            blockstamp,
            network_validators,
            lido_validators,
            [Gwei(500 * 10**9)],
        )

        assert result is False

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ('activation_epoch_offset', 'exit_epoch_offset', 'withdrawable_epoch_offset', 'expected'),
        [
            (0, None, 1, True),
            (1, None, 2, False),
            (-1, None, 1, True),
            (-1, None, 0, False),
            (-2, -1, 1, True),
        ],
    )
    def test_is_slashing_impact_big_enough__lido_exposure_boundary__includes_expected_validator(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
        activation_epoch_offset: int,
        exit_epoch_offset: int | None,
        withdrawable_epoch_offset: int,
        expected: bool,
    ) -> None:
        subject = make_lido_validator(
            2_048 * 10**9,
            slashed=True,
            activation_epoch=blockstamp.ref_epoch + activation_epoch_offset,
            exit_epoch=(FAR_FUTURE_EPOCH if exit_epoch_offset is None else blockstamp.ref_epoch + exit_epoch_offset),
            withdrawable_epoch=blockstamp.ref_epoch + withdrawable_epoch_offset,
        )
        baseline = make_lido_validator(2_048 * 10**9)
        configure_slashing_impact(bunker, base_rate_ppm=1_000_000, threshold_ppm=500_000)

        result = bunker.is_slashing_impact_big_enough(
            blockstamp,
            [make_network_validator(2_048 * 10**9)],
            [subject, baseline],
            [],
        )

        assert result is expected

    @pytest.mark.unit
    def test_is_slashing_impact_big_enough__network_factor_above_one__caps_factor(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
    ) -> None:
        lido_validators = [make_lido_validator(1 * 10**9, slashed=True), make_lido_validator(99 * 10**9)]
        network_validators = [make_network_validator(100 * 10**9)]
        configure_slashing_impact(bunker, base_rate_ppm=0, threshold_ppm=10_001)

        result = bunker.is_slashing_impact_big_enough(
            blockstamp,
            network_validators,
            lido_validators,
            [Gwei(40 * 10**9)],
        )

        assert result is False

    @pytest.mark.unit
    def test_is_slashing_impact_big_enough__lido_slashing_in_network_vector__uses_both_components(
        self,
        bunker: BunkerService,
        blockstamp: ReferenceBlockStamp,
    ) -> None:
        lido_validators = [make_lido_validator(10 * 10**9, slashed=True), make_lido_validator(90 * 10**9)]
        network_validators = [make_network_validator(1_000 * 10**9)]
        configure_slashing_impact(bunker, base_rate_ppm=5_000, threshold_ppm=3_500)

        result = bunker.is_slashing_impact_big_enough(
            blockstamp,
            network_validators,
            lido_validators,
            [Gwei(10 * 10**9)],
        )

        assert result is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ('simulated_post_total_pooled_ether', 'expected'),
    [
        (15 * 10**18, False),
        (12 * 10**18, True),
        (18 * 10**18, False),
    ],
)
def test_is_negative_cl_rebase__simulated_total_pooled_ether__compares_with_pre_report_value(
    bunker: BunkerService,
    blockstamp: ReferenceBlockStamp,
    simulated_post_total_pooled_ether: int,
    expected: bool,
) -> None:
    bunker.w3.lido_contracts.lido.total_supply = Mock(return_value=15 * 10**18)
    simulated_cl_rebase = ReportSimulationResults(
        withdrawals_vault_transfer=Wei(0),
        el_rewards_vault_transfer=Wei(0),
        post_total_pooled_ether=simulated_post_total_pooled_ether,
        post_total_shares=0,
        ether_to_finalize_wq=0,
        shares_to_finalize_wq=0,
        shares_to_burn_for_withdrawals=0,
        total_shares_to_burn=0,
        shares_to_mint_as_fees=0,
        fee_distribution=ReportSimulationFeeDistribution(
            module_fee_recipients=[],
            module_ids=[],
            module_shares_to_mint=[],
            treasury_shares_to_mint=0,
        ),
        pre_total_shares=0,
        pre_total_pooled_ether=0,
        principal_cl_balance=0,
        post_internal_shares=0,
        post_internal_ether=0,
    )

    result = bunker.is_negative_cl_rebase(blockstamp, simulated_cl_rebase)

    assert result is expected
