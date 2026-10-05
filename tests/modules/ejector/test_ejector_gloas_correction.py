from typing import cast
from unittest.mock import Mock

import pytest

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MIN_ACTIVATION_BALANCE,
)
from src.modules.oracles.ejector.ejector import Ejector
from src.modules.oracles.ejector.sweep import get_validators_withdrawals
from src.providers.consensus.types import ExpectedWithdrawal
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, SlotNumber, ValidatorIndex, Wei
from src.utils.units import gwei_to_wei
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


SLOTS_PER_EPOCH = 32


def _corrected_balance(raw_balance: Gwei, in_flight: Gwei) -> Gwei:
    """The balance a validator reaches the ejector with: `indexed_validators` adds in-flight back."""
    state = BeaconStateViewFactory.build(
        validators=[ValidatorStateFactory.build()],
        balances=[raw_balance],
        slashings=[],
        payload_expected_withdrawals=[ExpectedWithdrawal(validator_index=ValidatorIndex(0), amount=in_flight)],
    )
    return state.indexed_validators[0].balance


def _validator(balance: Gwei, max_effective_balance: int, withdrawable_epoch: int = FAR_FUTURE_EPOCH) -> LidoValidator:
    built = LidoValidatorFactory.build_with_balance(balance, max_effective_balance)
    built.validator.withdrawable_epoch = withdrawable_epoch
    return LidoValidator(
        index=ValidatorIndex(1),
        balance=balance,
        validator=built.validator,
        lido_id=built.lido_id,
        pending_topups=[],
        consolidating_as_source=None,
        consolidating_as_target=[],
    )


def _ref_bs() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.fixture
def ejector(web3: Web3) -> Ejector:
    web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(return_value=1)
    return Ejector(web3)


@pytest.mark.unit
class TestPredictedElBalanceWithInFlightWithdrawals:
    @pytest.fixture(autouse=True)
    def only_cl_balance_terms(self, ejector: Ejector) -> None:
        """Zeroes everything the prediction adds on top of the CL-balance terms."""
        ejector.get_chain_config = Mock(return_value=Mock(slots_per_epoch=SLOTS_PER_EPOCH))
        ejector._get_total_el_balance = Mock(return_value=Wei(0))
        ejector._get_sweep_delay_in_epochs = Mock(return_value=0)
        ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))
        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=Wei(0))
        ejector.validators_state_service.get_recently_requested_but_not_exiting_validators = Mock(return_value=[])

    def test_get_predicted_el_balance__in_flight_full_withdrawal__counted_once(self, ejector):
        blockstamp = _ref_bs()
        balance = _corrected_balance(Gwei(0), MIN_ACTIVATION_BALANCE)
        validator = _validator(balance, MAX_EFFECTIVE_BALANCE, withdrawable_epoch=blockstamp.ref_epoch - 1)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(blockstamp.ref_epoch))

        assert ejector._get_predicted_el_balance(Gwei(0), blockstamp) == gwei_to_wei(MIN_ACTIVATION_BALANCE)

    def test_get_predicted_el_balance__validator_going_to_exit__in_flight_counted_once(self, ejector):
        # The validator is both active-Lido and recently-requested-to-exit.
        in_flight = Gwei(1000 * 10**9)
        balance = _corrected_balance(Gwei(MAX_EFFECTIVE_BALANCE_ELECTRA - in_flight), in_flight)
        validator = _validator(balance, MAX_EFFECTIVE_BALANCE_ELECTRA)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        ejector.validators_state_service.get_recently_requested_but_not_exiting_validators = Mock(
            return_value=[validator]
        )
        blockstamp = _ref_bs()
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(blockstamp.ref_epoch))

        result = ejector._get_predicted_el_balance(Gwei(0), blockstamp)

        assert result == gwei_to_wei(Gwei(MAX_EFFECTIVE_BALANCE_ELECTRA))

    def test_get_predicted_el_balance__in_flight_skim_of_staying_validator__not_counted(self, ejector):
        # Accepted trade-off: an in-flight excess skim of a validator that is neither withdrawable nor
        # exiting is in no balance term until the payload credits it on the EL.
        balance = _corrected_balance(MIN_ACTIVATION_BALANCE, Gwei(10**8))
        validator = _validator(balance, MAX_EFFECTIVE_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        blockstamp = _ref_bs()
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(blockstamp.ref_epoch))

        assert ejector._get_predicted_el_balance(Gwei(0), blockstamp) == Wei(0)


@pytest.mark.unit
class TestSweepReadsRawBalances:
    @staticmethod
    def _state(raw_balance: Gwei, withdrawals: list[ExpectedWithdrawal]):
        return BeaconStateViewFactory.build(
            slot=SlotNumber(10 * SLOTS_PER_EPOCH),
            validators=[ValidatorStateFactory.build(withdrawable_epoch=EpochNumber(1))],
            balances=[raw_balance],
            slashings=[],
            payload_expected_withdrawals=withdrawals,
        )

    def test_get_validators_withdrawals__withdrawable_validator__swept(self):
        withdrawals = get_validators_withdrawals(self._state(MIN_ACTIVATION_BALANCE, []), [], SLOTS_PER_EPOCH)

        assert [w.amount for w in withdrawals] == [MIN_ACTIVATION_BALANCE]

    def test_get_validators_withdrawals__in_flight_full_withdrawal__not_swept_again(self):
        # The sweep models the spec's next transition, so it must not see in-flight ETH as still on the CL.
        in_flight = [ExpectedWithdrawal(validator_index=ValidatorIndex(0), amount=MIN_ACTIVATION_BALANCE)]

        assert get_validators_withdrawals(self._state(Gwei(0), in_flight), [], SLOTS_PER_EPOCH) == []
