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
from src.providers.consensus.types import ExpectedWithdrawal
from src.types import EpochNumber, Gwei, ReferenceBlockStamp, ValidatorIndex, Wei
from src.utils.units import gwei_to_wei
from src.web3py.extensions.lido_validators import ConsolidationRequest, LidoValidator
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.consensus import BeaconStateViewFactory
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


def _compounding_validator(index: int, balance: Gwei) -> LidoValidator:
    """A 0x02 validator, whose max effective balance leaves room for an EIP-7002 partial
    withdrawal to move what `get_predictable_inbound_balance` reports."""
    built = LidoValidatorFactory.build_with_balance(balance, MAX_EFFECTIVE_BALANCE_ELECTRA)
    built.validator.withdrawable_epoch = FAR_FUTURE_EPOCH
    return LidoValidator(
        index=ValidatorIndex(index),
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


def _set_in_flight(ejector: Ejector, withdrawals: list[ExpectedWithdrawal]) -> None:
    ejector.w3.cc.get_state_view = Mock(
        return_value=BeaconStateViewFactory.build_without_validators(payload_expected_withdrawals=withdrawals)
    )


@pytest.mark.unit
class TestWithdrawableLidoValidatorsBalanceCorrection:
    def test_get_withdrawable_lido_validators_balance__in_flight_full_withdrawal__added_back(self, ejector):
        # A zero CL balance fails the `balance > 0` arm of is_fully_withdrawable_validator.
        on_epoch = EpochNumber(100)
        validator = _validator(1, Gwei(0), withdrawable_epoch=on_epoch - 1)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(32 * 10**9))])

        result = ejector._get_withdrawable_lido_validators_balance(on_epoch, _ref_bs())

        assert result == Wei(32 * 10**18)

    def test_get_withdrawable_lido_validators_balance__in_flight_partial_sweep__restores_excess(self, ejector):
        excess = Gwei(3 * 10**9)
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=excess)])

        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        assert result == Wei(excess * 10**9)

    def test_get_withdrawable_lido_validators_balance__duplicate_indices__summed(self, ejector):
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(
            ejector,
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10**9)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(2 * 10**9)),
            ],
        )

        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        assert result == Wei(3 * 10**18)

    def test_get_withdrawable_lido_validators_balance__foreign_and_builder_entries__ignored(self, ejector):
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(
            ejector,
            [
                ExpectedWithdrawal(validator_index=ValidatorIndex(99), amount=Gwei(5 * 10**9)),
                ExpectedWithdrawal(validator_index=ValidatorIndex(BUILDER_INDEX_FLAG + 7), amount=Gwei(9 * 10**9)),
            ],
        )

        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        assert result == Wei(0)

    def test_get_withdrawable_lido_validators_balance__consolidation_source__not_corrected(self, ejector):
        # The surrounding sum skips consolidation sources, so the add-back must too.
        validator = _validator(1, MIN_ACTIVATION_BALANCE, consolidating_as_source=Mock(spec=ConsolidationRequest))
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=Gwei(10**9))])

        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        assert result == Wei(0)

    def test_get_withdrawable_lido_validators_balance__pre_fork_state__unchanged(self, ejector):
        validator = _validator(1, MIN_ACTIVATION_BALANCE)
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        _set_in_flight(ejector, [])

        result = ejector._get_withdrawable_lido_validators_balance(EpochNumber(100), _ref_bs())

        assert result == Wei(0)


@pytest.mark.unit
class TestNoDoubleCounting:
    """`going_to_withdraw` and `future_withdrawals` are complementary halves of one balance, so
    correcting the going-to-exit subset in both counted the same ETH twice."""

    def test_get_predicted_el_balance__validator_going_to_exit__in_flight_added_back_once(self, ejector):
        # The validator is both active-Lido and recently-requested-to-exit, so its in-flight
        # withdrawal reaches both terms.
        in_flight = Gwei(1000 * 10**9)
        validator = _compounding_validator(1, Gwei(MAX_EFFECTIVE_BALANCE_ELECTRA - in_flight))
        ejector.w3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
        ejector.validators_state_service.get_recently_requested_but_not_exiting_validators = Mock(
            return_value=[validator]
        )
        _set_in_flight(ejector, [ExpectedWithdrawal(validator_index=ValidatorIndex(1), amount=in_flight)])

        # Everything the prediction adds on top of the two CL-balance terms is zeroed out.
        ejector.get_chain_config = Mock(return_value=Mock(slots_per_epoch=32))
        ejector._get_total_el_balance = Mock(return_value=Wei(0))
        ejector._get_sweep_delay_in_epochs = Mock(return_value=0)
        ejector._get_deposit_lock_amount = Mock(return_value=Wei(0))
        ejector.prediction_service.get_rewards_per_epoch = Mock(return_value=Wei(0))
        blockstamp = _ref_bs()
        ejector._get_predicted_withdrawable_epoch = Mock(return_value=EpochNumber(blockstamp.ref_epoch))

        result = ejector._get_predicted_el_balance(Gwei(0), blockstamp)

        # The two terms reconstruct the pre-deduction balance, not one batch more.
        assert result == gwei_to_wei(Gwei(MAX_EFFECTIVE_BALANCE_ELECTRA))
