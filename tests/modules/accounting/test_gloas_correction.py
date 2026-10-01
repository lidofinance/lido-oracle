from typing import cast
from unittest.mock import Mock

import pytest

from src.modules.oracles.accounting.accounting import Accounting
from src.providers.consensus.types import BeaconStateView, ExpectedWithdrawal, Validator
from src.types import Gwei, ReferenceBlockStamp, StakingModuleId, ValidatorIndex
from src.web3py.extensions.lido_validators import NodeOperatorId
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import ValidatorStateFactory


BUILDER_INDEX_FLAG = 2**40


@pytest.fixture
def accounting(web3):
    return Accounting(web3)


def _state(balances: list[int], withdrawals: list[ExpectedWithdrawal]) -> BeaconStateView:
    return BeaconStateViewFactory.build(
        validators=[ValidatorStateFactory.build(effective_balance=Gwei(32)) for _ in balances],
        balances=[Gwei(b) for b in balances],
        slashings=[],
        payload_expected_withdrawals=withdrawals,
    )


def _withdrawal(index: int, amount: int) -> ExpectedWithdrawal:
    return ExpectedWithdrawal(validator_index=ValidatorIndex(index), amount=Gwei(amount))


def _balances(validators: list[Validator]) -> list[Gwei]:
    return [v.balance for v in validators]


@pytest.mark.unit
class TestIndexedValidatorsInFlightCorrection:
    def test_indexed_validators__in_flight_withdrawal__added_back(self):
        state = _state([100, 0, 300], [_withdrawal(1, 32), _withdrawal(2, 5)])

        assert _balances(state.indexed_validators) == [Gwei(100), Gwei(32), Gwei(305)]

    def test_indexed_validators__duplicate_indices__summed(self):
        state = _state([100], [_withdrawal(0, 10), _withdrawal(0, 25)])

        assert _balances(state.indexed_validators) == [Gwei(135)]

    def test_indexed_validators__builder_entry__matches_no_validator(self):
        state = _state([100], [_withdrawal(BUILDER_INDEX_FLAG + 0, 1000)])

        assert _balances(state.indexed_validators) == [Gwei(100)]

    def test_indexed_validators__pre_gloas_state__balances_unchanged(self):
        state = _state([100, 200], [])

        assert _balances(state.indexed_validators) == [Gwei(100), Gwei(200)]

    def test_indexed_validators__in_flight_withdrawal__raw_state_untouched(self):
        # Spec modelling (e.g. the withdrawals sweep) reads `balances` and `effective_balance` as on chain.
        state = _state([0], [_withdrawal(0, 32)])

        _ = state.indexed_validators

        assert state.balances == [Gwei(0)]
        assert state.indexed_validators[0].validator.effective_balance == Gwei(32)


def _ref_bs() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.mark.unit
class TestAccountingReadsCorrectedBalances:
    def test_get_cl_validators_balance__in_flight_withdrawal__included(self, accounting):
        state = _state([100, 200], [_withdrawal(0, 50)])
        accounting.w3.lido_validators.get_active_lido_validators = Mock(return_value=state.indexed_validators)

        result = accounting._get_cl_validators_balance(_ref_bs())

        assert result == Gwei(100 + 200 + 50)

    def test_get_balances_by_modules__in_flight_withdrawal__attributed_to_its_module(self, accounting):
        state = _state([100, 300], [_withdrawal(0, 10), _withdrawal(1, 20), _withdrawal(BUILDER_INDEX_FLAG, 999)])
        sm1 = Mock(staking_module_address='addr1', id=StakingModuleId(1))
        sm2 = Mock(staking_module_address='addr2', id=StakingModuleId(2))
        accounting.w3.lido_contracts.staking_router.get_staking_modules_by_address = Mock(
            return_value={'addr1': sm1, 'addr2': sm2}
        )
        first, second = state.indexed_validators
        accounting.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
            return_value={
                (StakingModuleId(1), NodeOperatorId(0)): [first],
                (StakingModuleId(2), NodeOperatorId(0)): [second],
            }
        )

        sm_ids, balances = accounting._get_balances_by_modules(_ref_bs())

        assert sm_ids == [StakingModuleId(1), StakingModuleId(2)]
        assert balances == [Gwei(110), Gwei(320)]
