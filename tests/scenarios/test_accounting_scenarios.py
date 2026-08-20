"""Report-golden scenarios for the accounting module (framework Layer 1).

These scenarios build the complete 19-field report through ``Accounting.build_report``. The
Gloas-sensitive CL total and per-module balances use their real implementations; unrelated report
inputs are fixed at the data-collection seams so the expected tuple remains deterministic.
"""

from typing import cast
from unittest.mock import Mock

import pytest
from web3.types import Wei

from src.modules.common.types import ZERO_HASH
from src.modules.oracles.accounting.accounting import Accounting
from src.modules.oracles.accounting.third_phase.types import ExtraData, FormatList
from src.modules.oracles.accounting.types import FinalizationShareRate, Shares, VaultsTreeCid, VaultsTreeRoot
from src.providers.consensus.types import ExpectedWithdrawal
from src.types import Gwei, ReferenceBlockStamp, StakingModuleId, ValidatorIndex
from src.web3py.extensions.lido_validators import NodeOperatorId
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.scenarios.invariants import check_accounting_report_wellformed


CONSENSUS_VERSION = 6
BUILDER_INDEX_FLAG = 2**40


def _ref_blockstamp(*, correction_needed: bool) -> ReferenceBlockStamp:
    return cast(
        ReferenceBlockStamp,
        ReferenceBlockStampFactory.build(withdrawal_correction_needed=correction_needed),
    )


def _configure_report_inputs(accounting: Accounting, *, is_gloas: bool, withdrawals: list[ExpectedWithdrawal]) -> Mock:
    validators = [
        Mock(index=ValidatorIndex(1), balance=Gwei(100)),
        Mock(index=ValidatorIndex(2), balance=Gwei(300)),
    ]
    staking_modules = {
        'module-1': Mock(staking_module_address='module-1', id=StakingModuleId(1)),
        'module-2': Mock(staking_module_address='module-2', id=StakingModuleId(2)),
    }

    get_state_view = Mock(return_value=Mock(payload_expected_withdrawals=withdrawals))
    accounting.w3.cc.is_gloas = Mock(return_value=is_gloas)
    accounting.w3.cc.get_state_view = get_state_view
    accounting.w3.lido_validators.get_active_lido_validators = Mock(return_value=validators)
    accounting.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            (StakingModuleId(1), NodeOperatorId(0)): [validators[0]],
            (StakingModuleId(2), NodeOperatorId(0)): [validators[1]],
        }
    )
    accounting.w3.lido_contracts.staking_router.get_staking_modules_by_address = Mock(return_value=staking_modules)

    accounting.get_consensus_version = Mock(return_value=CONSENSUS_VERSION)
    accounting._get_cl_pending_validators_balance = Mock(return_value=Gwei(500))
    accounting._get_newly_exited_validators_by_modules = Mock(return_value=([StakingModuleId(2)], [4]))
    accounting.w3.lido_contracts.get_withdrawal_balance = Mock(return_value=Wei(700))
    accounting.w3.lido_contracts.get_el_vault_balance = Mock(return_value=Wei(800))
    accounting.get_shares_to_burn = Mock(return_value=Shares(90))
    accounting._get_finalization_data = Mock(return_value=([11, 12], FinalizationShareRate(10**27)))
    accounting._is_bunker = Mock(return_value=False)
    accounting._handle_vaults_report = Mock(return_value=(VaultsTreeRoot(ZERO_HASH), VaultsTreeCid('')))
    accounting.get_extra_data = Mock(return_value=_empty_extra_data())
    accounting._update_metrics = Mock()
    return get_state_view


def _empty_extra_data() -> ExtraData:
    return ExtraData(
        extra_data_list=[],
        data_hash=ZERO_HASH,
        format=FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value,
        items_count=0,
    )


def _expected_report(
    ref_slot: int,
    module_balances: list[Gwei],
    *,
    extra_data_format: int = FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value,
    extra_data_hash: bytes = ZERO_HASH,
    extra_data_items_count: int = 0,
) -> tuple:
    return (
        CONSENSUS_VERSION,
        ref_slot,
        Gwei(sum(module_balances)),
        Gwei(500),
        [StakingModuleId(2)],
        [4],
        [StakingModuleId(1), StakingModuleId(2)],
        module_balances,
        Wei(700),
        Wei(800),
        Shares(90),
        [11, 12],
        FinalizationShareRate(10**27),
        False,
        VaultsTreeRoot(ZERO_HASH),
        VaultsTreeCid(''),
        extra_data_format,
        extra_data_hash,
        extra_data_items_count,
    )


@pytest.fixture()
def accounting(web3: Web3) -> Accounting:
    return Accounting(web3)


@pytest.mark.unit
@pytest.mark.scenario
class TestAccountingReportScenarios:
    def test_build_report__prefork_with_fallback_flag__keeps_gloas_paths_inert(self, accounting: Accounting) -> None:
        # Arrange — AC-00: even a true correction flag must be inert before the fork gate.
        blockstamp = _ref_blockstamp(correction_needed=True)
        get_state_view = _configure_report_inputs(
            accounting,
            is_gloas=False,
            withdrawals=[ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10))],
        )

        # Act
        report = accounting.build_report(blockstamp)

        # Assert
        assert report == _expected_report(blockstamp.ref_slot, [Gwei(100), Gwei(300)])
        check_accounting_report_wellformed(report)
        get_state_view.assert_not_called()

    def test_build_report__gloas_payload_confirmed__does_not_double_count_withdrawals(
        self, accounting: Accounting
    ) -> None:
        # Arrange — AC-01: Y == ref_slot, so the withdrawal vault already contains the payload credit.
        blockstamp = _ref_blockstamp(correction_needed=False)
        get_state_view = _configure_report_inputs(
            accounting,
            is_gloas=True,
            withdrawals=[ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10))],
        )

        # Act
        report = accounting.build_report(blockstamp)

        # Assert
        assert report == _expected_report(blockstamp.ref_slot, [Gwei(100), Gwei(300)])
        check_accounting_report_wellformed(report)
        get_state_view.assert_not_called()

    def test_build_report__gloas_payload_withheld__corrects_total_and_module_balances(
        self, accounting: Accounting
    ) -> None:
        # Arrange — AC-02: Y < ref_slot and both Lido modules have in-flight withdrawals.
        blockstamp = _ref_blockstamp(correction_needed=True)
        _configure_report_inputs(
            accounting,
            is_gloas=True,
            withdrawals=[
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
            ],
        )

        # Act
        report = accounting.build_report(blockstamp)

        # Assert
        assert report == _expected_report(blockstamp.ref_slot, [Gwei(110), Gwei(320)])
        check_accounting_report_wellformed(report)

    def test_build_report__withheld_payload_has_builder_entry__excludes_builder_from_correction(
        self, accounting: Accounting
    ) -> None:
        # Arrange — AC-03: builder registry indices are not validator indices and must be ignored.
        blockstamp = _ref_blockstamp(correction_needed=True)
        _configure_report_inputs(
            accounting,
            is_gloas=True,
            withdrawals=[
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(1_000)),
            ],
        )

        # Act
        report = accounting.build_report(blockstamp)

        # Assert
        assert report == _expected_report(blockstamp.ref_slot, [Gwei(110), Gwei(300)])
        check_accounting_report_wellformed(report)

    def test_build_report__one_newly_exited_operator__encodes_nonempty_extra_data(self, accounting: Accounting) -> None:
        # Arrange — AC-07: one operator update is encoded by the real ExtraDataService path.
        blockstamp = _ref_blockstamp(correction_needed=False)
        _configure_report_inputs(accounting, is_gloas=True, withdrawals=[])
        del accounting.get_extra_data
        accounting.lido_validator_state_service.get_lido_newly_exited_validators = Mock(
            return_value={(StakingModuleId(2), NodeOperatorId(7)): 3}
        )
        accounting.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
            return_value=Mock(max_items_per_extra_data_transaction=2, max_node_operators_per_extra_data_item=10)
        )

        expected_transaction = (
            ZERO_HASH
            + (0).to_bytes(3)
            + (2).to_bytes(2)
            + (2).to_bytes(3)
            + (1).to_bytes(8)
            + (7).to_bytes(8)
            + (3).to_bytes(16)
        )
        expected_hash = Web3.keccak(expected_transaction)

        # Act
        report = accounting.build_report(blockstamp)
        extra_data = accounting.get_extra_data(blockstamp)

        # Assert
        assert report == _expected_report(
            blockstamp.ref_slot,
            [Gwei(100), Gwei(300)],
            extra_data_format=FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value,
            extra_data_hash=expected_hash,
            extra_data_items_count=1,
        )
        assert extra_data.extra_data_list == [expected_transaction]
        check_accounting_report_wellformed(report)
