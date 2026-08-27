from typing import cast
from unittest.mock import Mock

import pytest

from src.modules.oracles.accounting.accounting import Accounting
from src.providers.consensus.types import BeaconStateView, ExpectedWithdrawal
from src.types import Gwei, ReferenceBlockStamp, StakingModuleId, ValidatorIndex
from src.web3py.extensions.lido_validators import NodeOperatorId
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.consensus import BeaconStateViewFactory


BUILDER_INDEX_FLAG = 2**40


@pytest.fixture
def accounting(web3):
    return Accounting(web3)


def _state(withdrawals: list[ExpectedWithdrawal]) -> BeaconStateView:
    return BeaconStateViewFactory.build_without_validators(payload_expected_withdrawals=withdrawals)


@pytest.mark.unit
class TestInFlightWithdrawalSum:
    def test_in_flight_withdrawal_sum__sums_only_matching_lido_indices(self):
        state = _state(
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(3), amount=Gwei(99)),
            ]
        )
        assert state.in_flight_withdrawal_sum({ValidatorIndex(1), ValidatorIndex(2)}) == Gwei(30)

    def test_in_flight_withdrawal_sum__excludes_builder_registry_entries(self):
        # A builder entry: its index carries BUILDER_INDEX_FLAG and is never a Lido validator.
        state = _state(
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(5), amount=Gwei(40)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(1000)),
            ]
        )
        assert state.in_flight_withdrawal_sum({ValidatorIndex(5)}) == Gwei(40)

    def test_in_flight_withdrawal_sum__pre_gloas_state__returns_zero(self):
        assert _state([]).in_flight_withdrawal_sum({ValidatorIndex(1)}) == Gwei(0)

    def test_in_flight_withdrawal_sum__duplicate_indices__summed(self):
        state = _state(
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(25)),
            ]
        )
        assert state.in_flight_withdrawal_sum({ValidatorIndex(1)}) == Gwei(35)


@pytest.mark.unit
class TestInFlightWithdrawals:
    def test_in_flight_withdrawals__duplicate_indices__summed_not_overwritten(self):
        state = _state(
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(25)),
            ]
        )
        assert state.in_flight_withdrawals == {ValidatorIndex(1): Gwei(35), ValidatorIndex(2): Gwei(20)}

    def test_in_flight_withdrawals__pre_gloas_state__returns_empty_mapping(self):
        assert _state([]).in_flight_withdrawals == {}


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
        accounting.w3.cc.get_state_view = Mock(return_value=_state(withdrawals))

    def test_get_cl_validators_balance__in_flight_withdrawal__added_back(self, accounting):
        self._setup(accounting, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50))])

        result = accounting._get_cl_validators_balance(_ref_bs())

        assert result == Gwei(100 + 200 + 50)

    def test_get_cl_validators_balance__withdrawal_for_foreign_validator__not_added_back(self, accounting):
        self._setup(accounting, [ExpectedWithdrawal(validator_index=ValidatorIndex(99), amount=Gwei(50))])

        result = accounting._get_cl_validators_balance(_ref_bs())

        assert result == Gwei(300)

    def test_get_cl_validators_balance__pre_fork_state__no_correction(self, accounting):
        self._setup(accounting, [])

        result = accounting._get_cl_validators_balance(_ref_bs())

        assert result == Gwei(300)


@pytest.mark.unit
class TestBalancesByModulesCorrection:
    def test_get_balances_by_modules__correction_attributed_per_module__sum_matches_total(self, accounting):
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
            return_value=_state(
                [
                    ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10)),
                    ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(20)),
                    # A builder-registry entry, never attributable to a module.
                    ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(999)),
                ]
            )
        )

        sm_ids, balances = accounting._get_balances_by_modules(_ref_bs())

        assert sm_ids == [StakingModuleId(1), StakingModuleId(2)]
        assert balances == [Gwei(110), Gwei(320)]
        assert sum(balances) == Gwei(100 + 300 + 10 + 20)
