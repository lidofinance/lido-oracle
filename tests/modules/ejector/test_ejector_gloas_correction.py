from typing import cast

import pytest

from src.constants import (
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MIN_ACTIVATION_BALANCE,
)
from src.providers.consensus.types import ExpectedWithdrawal
from src.services.validator_state import InFlightWithdrawals, get_in_flight_inbound
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, ValidatorIndex
from src.web3py.extensions.lido_validators import LidoValidator
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
    built.validator.slashed = False
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


@pytest.mark.unit
class TestInFlightInboundWithInFlightPayloadWithdrawals:
    def test_get_in_flight_inbound__in_flight_full_withdrawal__counted_once(self):
        blockstamp = _ref_bs()
        balance = _corrected_balance(Gwei(0), MIN_ACTIVATION_BALANCE)
        validator = _validator(balance, MAX_EFFECTIVE_BALANCE, withdrawable_epoch=blockstamp.ref_epoch - 1)
        validator.validator.exit_epoch = EpochNumber(blockstamp.ref_epoch - 257)

        result = get_in_flight_inbound([validator], InFlightWithdrawals())

        assert result.amount == MIN_ACTIVATION_BALANCE

    def test_get_in_flight_inbound__queued_full_withdrawal__in_flight_counted_once(self):
        in_flight = Gwei(1000 * 10**9)
        balance = _corrected_balance(Gwei(MAX_EFFECTIVE_BALANCE_ELECTRA - in_flight), in_flight)
        validator = _validator(balance, MAX_EFFECTIVE_BALANCE_ELECTRA)

        result = get_in_flight_inbound([validator], InFlightWithdrawals(fwr_validators=frozenset({validator.index})))

        assert result.amount == MAX_EFFECTIVE_BALANCE_ELECTRA

    def test_get_in_flight_inbound__in_flight_skim_of_staying_validator__not_counted(self):
        # Accepted trade-off: an in-flight excess skim of a validator with no request is in no
        # balance term until the payload credits it on the EL.
        validator = _validator(_corrected_balance(MIN_ACTIVATION_BALANCE, Gwei(10**8)), MAX_EFFECTIVE_BALANCE)

        assert get_in_flight_inbound([validator], InFlightWithdrawals()).amount == Gwei(0)
