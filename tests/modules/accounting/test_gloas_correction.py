from typing import cast
from unittest.mock import Mock

import pytest

from src.modules.oracles.accounting.accounting import Accounting
from src.providers.consensus.types import ExpectedWithdrawal
from src.types import Gwei, ReferenceBlockStamp, StakingModuleId, ValidatorIndex
from src.utils.validator_balance import gloas_balance_correction, gloas_correction_by_index
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

    def test_gloas_balance_correction__duplicate_indices__summed(self):
        withdrawals = [
            ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
            ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(25)),
        ]
        assert gloas_balance_correction(withdrawals, {ValidatorIndex(1)}) == Gwei(35)


@pytest.mark.unit
class TestGloasCorrectionByIndex:
    def test_gloas_correction_by_index__duplicate_indices__summed_not_overwritten(self):
        withdrawals = [
            ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
            ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
            ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(25)),
        ]
        assert gloas_correction_by_index(withdrawals) == {ValidatorIndex(1): Gwei(35), ValidatorIndex(2): Gwei(20)}

    def test_gloas_correction_by_index__empty__returns_empty_mapping(self):
        assert gloas_correction_by_index([]) == {}


def _ref_bs() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.mark.unit
class TestClValidatorsBalanceCorrection:
    def _setup(self, accounting, withdrawals):
        validators = [
            Mock(index=ValidatorIndex(1), balance=Gwei(100)),
            Mock(index=ValidatorIndex(2), balance=Gwei(200)),
        ]
        accounting.w3.lido_validators.get_active_lido_validators = Mock(return_value=validators)
        accounting.w3.cc.get_state_view = Mock(return_value=Mock(payload_expected_withdrawals=withdrawals))

    def test_get_cl_validators_balance__in_flight_withdrawal__added_back(self, accounting):
        # Arrange
        self._setup(accounting, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50))])

        # Act
        result = accounting._get_cl_validators_balance(_ref_bs())

        # Assert
        assert result == Gwei(100 + 200 + 50)

    def test_get_cl_validators_balance__withdrawal_for_foreign_validator__not_added_back(self, accounting):
        # Arrange
        self._setup(accounting, [ExpectedWithdrawal(validator_index=ValidatorIndex(99), amount=Gwei(50))])

        # Act
        result = accounting._get_cl_validators_balance(_ref_bs())

        # Assert
        assert result == Gwei(300)

    def test_get_cl_validators_balance__pre_fork_state__no_correction(self, accounting):
        # Arrange
        self._setup(accounting, [])

        # Act
        result = accounting._get_cl_validators_balance(_ref_bs())

        # Assert
        assert result == Gwei(300)


@pytest.mark.unit
class TestBalancesByModulesCorrection:
    def test_get_balances_by_modules__correction_attributed_per_module__sum_matches_total(self, accounting):
        # Arrange
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
        accounting.w3.cc.get_state_view = Mock(
            return_value=Mock(
                payload_expected_withdrawals=[
                    ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                    ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
                    # A builder-registry entry, never attributable to a module.
                    ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(999)),
                ]
            )
        )

        # Act
        sm_ids, balances = accounting._get_balances_by_modules(_ref_bs())

        # Assert
        assert sm_ids == [StakingModuleId(1), StakingModuleId(2)]
        assert balances == [Gwei(110), Gwei(320)]
        assert sum(balances) == Gwei(100 + 300 + 10 + 20)
