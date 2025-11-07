from typing import Iterable, Sequence
from unittest.mock import Mock

import pytest
from web3.types import Wei

from src.modules.accounting.types import ReportSimulationFeeDistribution, ReportSimulationResults
from src.providers.consensus.types import BeaconStateView
from src.services.bunker import BunkerService
from src.types import ReferenceBlockStamp
from src.web3py.extensions.lido_validators import LidoValidator
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import BunkerConfigFactory, ChainConfigFactory, FrameConfigFactory
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.contract_responses import ReportSimulationResultsFactory
from tests.factory.no_registry import LidoValidatorFactory
from tests.modules.accounting.bunker.conftest import simple_ref_blockstamp


class TestIsBunkerMode:
    @pytest.mark.unit
    @pytest.mark.usefixtures(
        "mock_get_config",
        "mock_get_state",
    )
    def test_false_when_no_prev_report(
        self,
        bunker: BunkerService,
        ref_blockstamp: ReferenceBlockStamp,
    ) -> None:
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=None)
        bunker.get_cl_rebase_for_current_report = Mock()
        result = bunker.is_bunker_mode(
            ref_blockstamp,
            FrameConfigFactory.build(),
            ChainConfigFactory.build(),
            ReportSimulationResultsFactory.build(),
        )
        assert result is False
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot.assert_called_once()
        bunker.get_cl_rebase_for_current_report.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.usefixtures(
        "mock_get_config",
        "mock_get_state",
    )
    def test_true_when_cl_rebase_is_negative(
        self,
        bunker: BunkerService,
        ref_blockstamp: ReferenceBlockStamp,
        is_high_midterm_slashing_penalty: Mock,
    ) -> None:
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=ref_blockstamp)
        bunker.w3.cc.get_config_spec = Mock()
        bunker.get_cl_rebase_for_current_report = Mock(return_value=-1)

        result = bunker.is_bunker_mode(
            ref_blockstamp,
            FrameConfigFactory.build(),
            ChainConfigFactory.build(),
            ReportSimulationResultsFactory.build(),
        )
        assert result is True

        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot.assert_called_once()
        bunker.get_cl_rebase_for_current_report.assert_called_once()
        is_high_midterm_slashing_penalty.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.usefixtures(
        "mock_get_config",
        "mock_get_state",
    )
    def test_true_when_high_midterm_slashing_penalty(
        self,
        bunker: BunkerService,
        ref_blockstamp: ReferenceBlockStamp,
        is_high_midterm_slashing_penalty: Mock,
        is_abnormal_cl_rebase: Mock,
    ) -> None:
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=ref_blockstamp)
        bunker.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock()
        bunker.w3.cc.get_config_spec = Mock()
        bunker.get_cl_rebase_for_current_report = Mock(return_value=0)
        is_high_midterm_slashing_penalty.return_value = True
        result = bunker.is_bunker_mode(
            ref_blockstamp,
            FrameConfigFactory.build(),
            ChainConfigFactory.build(),
            ReportSimulationResultsFactory.build(),
        )
        assert result is True
        is_high_midterm_slashing_penalty.assert_called_once()
        is_abnormal_cl_rebase.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.usefixtures(
        "mock_get_config",
        "mock_get_state",
    )
    def test_true_when_abnormal_cl_rebase(
        self,
        bunker: BunkerService,
        ref_blockstamp: ReferenceBlockStamp,
        is_high_midterm_slashing_penalty: Mock,
        is_abnormal_cl_rebase: Mock,
    ) -> None:
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=ref_blockstamp)
        bunker.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock()
        bunker.w3.cc.get_config_spec = Mock()
        bunker.get_cl_rebase_for_current_report = Mock(return_value=0)
        is_high_midterm_slashing_penalty.return_value = False
        is_abnormal_cl_rebase.return_value = True
        result = bunker.is_bunker_mode(
            ref_blockstamp,
            FrameConfigFactory.build(),
            ChainConfigFactory.build(),
            ReportSimulationResultsFactory.build(),
        )
        assert result is True
        is_high_midterm_slashing_penalty.assert_called_once()
        is_abnormal_cl_rebase.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.usefixtures(
        "mock_get_config",
        "mock_get_state",
        "mock_total_supply",
    )
    def test_no_bunker_mode_by_default(
        self,
        bunker: BunkerService,
        ref_blockstamp: ReferenceBlockStamp,
        is_high_midterm_slashing_penalty: Mock,
        is_abnormal_cl_rebase: Mock,
    ) -> None:
        bunker.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=ref_blockstamp)
        bunker.w3.lido_contracts.accounting_oracle.get_consensus_version = Mock()
        bunker.w3.cc.get_config_spec = Mock()
        bunker.get_cl_rebase_for_current_report = Mock(return_value=0)
        is_high_midterm_slashing_penalty.return_value = False
        is_abnormal_cl_rebase.return_value = False
        result = bunker.is_bunker_mode(
            ref_blockstamp,
            FrameConfigFactory.build(),
            ChainConfigFactory.build(),
            ReportSimulationResultsFactory.build(),
        )
        assert result is False
        is_high_midterm_slashing_penalty.assert_called_once()
        is_abnormal_cl_rebase.assert_called_once()

    # === fixtures === #

    @pytest.fixture
    def ref_blockstamp(self) -> ReferenceBlockStamp:
        return ReferenceBlockStampFactory.build()

    @pytest.fixture
    def mock_get_config(self, bunker: BunkerService) -> None:
        bunker._get_config = Mock(return_value=BunkerConfigFactory.build())

    @pytest.fixture
    def mock_validators(self, bunker: BunkerService) -> Sequence[LidoValidator]:
        validators = LidoValidatorFactory.batch(5)
        bunker.w3.cc.get_validators = Mock(return_value=validators)
        bunker.w3.lido_validators.get_lido_validators = Mock(return_value=validators[:2])
        return validators

    @pytest.fixture
    def mock_get_state(self, bunker: BunkerService, mock_validators) -> BeaconStateView:
        state = BeaconStateViewFactory.build_with_validators(validators=mock_validators, slashings=[])
        bunker.w3.cc.get_state_view = Mock(return_value=state)
        return state

    @pytest.fixture
    def mock_total_supply(self, bunker: BunkerService) -> None:
        bunker._get_total_supply = Mock(return_value=15 * 10**18)

    @pytest.fixture
    def is_high_midterm_slashing_penalty(self, monkeypatch: pytest.MonkeyPatch) -> Iterable[Mock]:
        mock = Mock()
        with monkeypatch.context() as m:
            m.setattr(
                "src.services.bunker.MidtermSlashingPenalty.is_high_midterm_slashing_penalty",
                mock,
            )
            yield mock

    @pytest.fixture
    def is_abnormal_cl_rebase(self, monkeypatch: pytest.MonkeyPatch) -> Iterable[Mock]:
        mock = Mock()
        with monkeypatch.context() as m:
            m.setattr(
                "src.services.bunker.AbnormalClRebase.is_abnormal_cl_rebase",
                mock,
            )
            yield mock


@pytest.mark.unit
@pytest.mark.parametrize(
    ("simulated_post_total_pooled_ether", "expected_rebase"),
    [
        (15 * 10**18, 0),
        (12 * 10**18, -3 * 10**9),
        (18 * 10**18, 3 * 10**9),
    ],
)
def test_get_cl_rebase_for_frame(
    bunker,
    simulated_post_total_pooled_ether,
    expected_rebase,
):
    bunker.w3.lido_contracts.lido.total_supply = Mock(return_value=15 * 10**18)

    blockstamp = simple_ref_blockstamp(0)
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

    result = bunker.get_cl_rebase_for_current_report(blockstamp, simulated_cl_rebase)

    assert result == expected_rebase
