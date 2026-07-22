"""Unit tests for the EIP-7732 (Gloas) in-flight withdrawal TVL correction (Accounting Oracle)."""

from typing import cast
from unittest.mock import Mock

import pytest

from src.modules.oracles.accounting.accounting import Accounting
from src.providers.consensus.types import ExpectedWithdrawal
from src.types import Gwei, ReferenceBlockStamp, StakingModuleId, ValidatorIndex
from src.utils.validator_balance import gloas_balance_correction
from src.web3py.extensions.lido_validators import NodeOperatorId
from tests.factory.blockstamp import ReferenceBlockStampFactory


BUILDER_INDEX_FLAG = 2**40


@pytest.fixture
def accounting(web3):
    return Accounting(web3)


@pytest.mark.unit
class TestGloasBalanceCorrection:
    def test_gloas_balance_correction__sums_only_matching_lido_indices(self):
        withdrawals = [
            ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
            ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
            ExpectedWithdrawal(validator_index=ValidatorIndex(3), amount=Gwei(99)),
        ]
        assert gloas_balance_correction(withdrawals, {ValidatorIndex(1), ValidatorIndex(2)}) == Gwei(30)

    def test_gloas_balance_correction__excludes_builder_registry_entries(self):
        # Builder-registry entries carry indices >= 2**40 and are never Lido validators.
        withdrawals = [
            ExpectedWithdrawal(validator_index=ValidatorIndex(5), amount=Gwei(40)),
            ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(1000)),
        ]
        assert gloas_balance_correction(withdrawals, {ValidatorIndex(5)}) == Gwei(40)

    def test_gloas_balance_correction__empty__returns_zero(self):
        assert gloas_balance_correction([], {ValidatorIndex(1)}) == Gwei(0)


def _ref_bs(correction_needed: bool) -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build(withdrawal_correction_needed=correction_needed))


@pytest.mark.unit
class TestClValidatorsBalanceCorrection:
    def _setup(self, accounting, *, is_gloas, withdrawals):
        validators = [
            Mock(index=ValidatorIndex(1), balance=Gwei(100)),
            Mock(index=ValidatorIndex(2), balance=Gwei(200)),
        ]
        accounting.w3.lido_validators.get_active_lido_validators = Mock(return_value=validators)
        accounting.w3.cc.is_gloas = Mock(return_value=is_gloas)
        accounting.w3.cc.get_state_view = Mock(return_value=Mock(payload_expected_withdrawals=withdrawals))

    def test_get_cl_validators_balance__gloas_and_correction_needed__adds_back(self, accounting):
        # Arrange: Y != ref_slot, so the withdrawal deducted from the CL balance must be added back.
        self._setup(
            accounting,
            is_gloas=True,
            withdrawals=[ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50))],
        )

        # Act
        result = accounting._get_cl_validators_balance(_ref_bs(correction_needed=True))

        # Assert
        assert result == Gwei(100 + 200 + 50)

    def test_get_cl_validators_balance__payload_confirmed_full__no_correction(self, accounting):
        # Arrange: Y == ref_slot -> vault already reflects the credit; applying it would double-count.
        self._setup(
            accounting,
            is_gloas=True,
            withdrawals=[ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50))],
        )

        # Act
        result = accounting._get_cl_validators_balance(_ref_bs(correction_needed=False))

        # Assert
        assert result == Gwei(300)
        accounting.w3.cc.get_state_view.assert_not_called()

    def test_get_cl_validators_balance__pre_fork__no_correction(self, accounting):
        # Arrange
        self._setup(
            accounting,
            is_gloas=False,
            withdrawals=[ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50))],
        )

        # Act
        result = accounting._get_cl_validators_balance(_ref_bs(correction_needed=True))

        # Assert
        assert result == Gwei(300)


@pytest.mark.unit
class TestBalancesByModulesCorrection:
    def test_get_balances_by_modules__correction_attributed_per_module__sum_matches_total(self, accounting):
        # Arrange: two modules, a withdrawal in-flight for a validator in each.
        sm1 = Mock(staking_module_address='addr1', id=StakingModuleId(1))
        sm2 = Mock(staking_module_address='addr2', id=StakingModuleId(2))
        accounting.w3.lido_contracts.staking_router.get_staking_modules_by_address = Mock(
            return_value={'addr1': sm1, 'addr2': sm2}
        )
        accounting.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
            return_value={
                (StakingModuleId(1), NodeOperatorId(0)): [Mock(index=ValidatorIndex(1), balance=Gwei(100))],
                (StakingModuleId(2), NodeOperatorId(0)): [Mock(index=ValidatorIndex(2), balance=Gwei(300))],
            }
        )
        accounting.w3.cc.is_gloas = Mock(return_value=True)
        accounting.w3.cc.get_state_view = Mock(
            return_value=Mock(
                payload_expected_withdrawals=[
                    ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                    ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
                ]
            )
        )

        # Act
        sm_ids, balances = accounting._get_balances_by_modules(_ref_bs(correction_needed=True))

        # Assert: correction is attributed per module and the per-module sum equals the corrected total.
        assert sm_ids == [StakingModuleId(1), StakingModuleId(2)]
        assert balances == [Gwei(110), Gwei(320)]
        assert sum(balances) == Gwei(100 + 300 + 10 + 20)
