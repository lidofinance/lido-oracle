"""Unit tests for the EIP-7732 (Gloas) in-flight withdrawal correction in the Ejector."""

from typing import cast
from unittest.mock import Mock

import pytest

from src.constants import FAR_FUTURE_EPOCH, MAX_EFFECTIVE_BALANCE, MIN_ACTIVATION_BALANCE
from src.modules.oracles.ejector.ejector import Ejector
from src.providers.consensus.types import ExpectedWithdrawal
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, ValidatorIndex, Wei
from src.web3py.extensions.lido_validators import ConsolidationRequest, LidoValidator
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory


BUILDER_INDEX_FLAG = 2**40


def _validator(
    index: int,
    balance: Gwei,
    withdrawable_epoch: int = FAR_FUTURE_EPOCH,
    consolidating_as_source: ConsolidationRequest | None = None,
) -> LidoValidator:
    """A Lido validator with no pending top-ups or consolidations, so balances flow through as-is."""
    built = LidoValidatorFactory.build_with_balance(balance, MAX_EFFECTIVE_BALANCE)
    built.validator.withdrawable_epoch = withdrawable_epoch
    return LidoValidator(
        index=ValidatorIndex(index),
        balance=balance,
        validator=built.validator,
        lido_id=built.lido_id,
        pending_topups=[],
        consolidating_as_source=consolidating_as_source,
        consolidating_as_target=[],
    )


def _ref_bs() -> ReferenceBlockStamp:
    return cast(ReferenceBlockStamp, ReferenceBlockStampFactory.build())


@pytest.fixture
def ejector(web3: Web3) -> Ejector:
    web3.lido_contracts.validators_exit_bus_oracle.get_consensus_version = Mock(return_value=1)
    return Ejector(web3)


def _set_in_flight(ejector: Ejector, withdrawals: list[ExpectedWithdrawal]) -> None:
    ejector.w3.cc.get_state_view = Mock(return_value=Mock(payload_expected_withdrawals=withdrawals))


@pytest.mark.unit
class TestWithdrawableLidoValidatorsBalanceCorrection:
    def test_get_withdrawable_lido_validators_balance__in_flight_full_withdrawal__added_back(self, ejector):
        # Arrange: an exited validator whose full payout is in flight has a zero CL balance, which
        # fails the `balance > 0` arm of is_fully_withdrawable_validator and contributes nothing.
        on_epoch = EpochNumber(100)
        validator = _validator(1, Gwei(0), withdrawable_epoch=on_epoch - 1)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(32 * 10**9))])

        # Act
        result = ejector._get_withdrawable_lido_validators_balance(on_epoch, _ref_bs())

        # Assert
        assert result == Wei(32 * 10**18)

    def test_get_withdrawable_lido_validators_balance__in_flight_partial_sweep__restores_excess(self, ejector):
        # Arrange: the sweep already took the excess above the max effective balance, so the term
        # this function is meant to report reads as zero.
        excess = Gwei(3 * 10**9)
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=excess)])

        # Act
        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        # Assert
        assert result == Wei(excess * 10**9)

    def test_get_withdrawable_lido_validators_balance__duplicate_indices__summed(self, ejector):
        # Arrange: one payload may carry a pending-partial entry and a sweep entry for one validator.
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(
            ejector,
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10**9)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(2 * 10**9)),
            ],
        )

        # Act
        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        # Assert
        assert result == Wei(3 * 10**18)

    def test_get_withdrawable_lido_validators_balance__foreign_and_builder_entries__ignored(self, ejector):
        # Arrange: withdrawals outside the protocol, and builder-registry entries (index >= 2**40).
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(
            ejector,
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(99), amount=Gwei(5 * 10**9)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(9 * 10**9)),
            ],
        )

        # Act
        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        # Assert
        assert result == Wei(0)

    def test_get_withdrawable_lido_validators_balance__consolidation_source__not_corrected(self, ejector):
        # Arrange: a consolidation source is skipped entirely, so its in-flight amount must not be
        # added back either — it is not part of this sum.
        validator = _validator(1, MIN_ACTIVATION_BALANCE, consolidating_as_source=Mock(spec=ConsolidationRequest))
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10**9))])

        # Act
        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        # Assert
        assert result == Wei(0)

    def test_get_withdrawable_lido_validators_balance__pre_fork_state__unchanged(self, ejector):
        # Arrange: pre-Gloas states carry no payload_expected_withdrawals at all.
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [])

        # Act
        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        # Assert
        assert result == Wei(0)


@pytest.mark.unit
class TestInFlightWithdrawals:
    def test_in_flight_withdrawals__no_matching_indices__returns_zero(self, ejector):
        # Arrange
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50))])

        # Act
        result = ejector._in_flight_withdrawals(_ref_bs(), set())

        # Assert
        assert result == Gwei(0)

    def test_in_flight_withdrawals__matching_indices__sums_amounts(self, ejector):
        # Arrange
        _set_in_flight(
            ejector,
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(50)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(2), amount=Gwei(70)),
            ],
        )

        # Act
        result = ejector._in_flight_withdrawals(_ref_bs(), {ValidatorIndex(1), ValidatorIndex(2)})

        # Assert
        assert result == Gwei(120)
