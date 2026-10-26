"""Tests for inbound-flow balance prediction.

These helpers decide how much ETH a validator is expected to end up with once the
CL has applied everything already queued for it: pending top-up deposits and
incoming consolidations. Both flows are invisible in `validator.balance` at the
reference slot, so getting them wrong silently mis-prices exits and withdrawals.
"""

import pytest

from src.constants import (
    COMPOUNDING_WITHDRAWAL_PREFIX,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    MAX_EFFECTIVE_BALANCE,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
)
from src.types import Gwei
from src.utils.validator_balance import (
    get_predictable_full_inbound_balance,
    get_predictable_inbound_balance,
    get_predictable_inbound_sweep,
)
from src.web3py.extensions.lido_validators import ConsolidationRequest
from tests.factory.no_registry import LidoValidatorFactory, PendingDepositFactory, ValidatorStateFactory


ETH = 10**9  # gwei per ETH


def _validator(balance_eth: float, *, compounding: bool = False, topups=None, incoming=None):
    """A Lido validator holding `balance_eth` with the given queued inbound flows."""
    prefix = COMPOUNDING_WITHDRAWAL_PREFIX if compounding else ETH1_ADDRESS_WITHDRAWAL_PREFIX
    balance = Gwei(int(balance_eth * ETH))
    return LidoValidatorFactory.build(
        balance=balance,
        validator=ValidatorStateFactory.build(
            withdrawal_credentials=prefix + '00' * 31,
            effective_balance=min(balance, MAX_EFFECTIVE_BALANCE_ELECTRA if compounding else MAX_EFFECTIVE_BALANCE),
        ),
        pending_topups=topups or [],
        consolidating_as_target=incoming or [],
    )


def _topup(amount_eth: float):
    return PendingDepositFactory.build(amount=Gwei(int(amount_eth * ETH)))


def _incoming_consolidation(amount_eth: float):
    return ConsolidationRequest(source_index=1, target_index=2, amount=Gwei(int(amount_eth * ETH)))


@pytest.mark.unit
class TestGetPredictableFullInboundBalance:
    """Uncapped sum: balance + every queued top-up + every incoming consolidation."""

    def test_full_inbound_balance__no_inbound_flows__returns_current_balance(self):
        # Arrange
        validator = _validator(32)
        # Act
        result = get_predictable_full_inbound_balance(validator)
        # Assert
        assert result == Gwei(32 * ETH)

    def test_full_inbound_balance__single_topup__adds_deposit_amount(self):
        # Arrange
        validator = _validator(32, topups=[_topup(8)])
        # Act
        result = get_predictable_full_inbound_balance(validator)
        # Assert
        assert result == Gwei(40 * ETH)

    def test_full_inbound_balance__multiple_topups__adds_every_deposit(self):
        # Arrange — a used key can accumulate several deposits in the queue
        validator = _validator(32, topups=[_topup(1), _topup(0.5), _topup(2.25)])
        # Act
        result = get_predictable_full_inbound_balance(validator)
        # Assert
        assert result == Gwei(int(35.75 * ETH))

    def test_full_inbound_balance__topups_and_consolidations__adds_both_flows(self):
        # Arrange
        validator = _validator(32, topups=[_topup(8)], incoming=[_incoming_consolidation(16)])
        # Act
        result = get_predictable_full_inbound_balance(validator)
        # Assert
        assert result == Gwei(56 * ETH)

    def test_full_inbound_balance__is_not_capped_by_max_effective_balance(self):
        # Arrange — 0x01 validator topped up far past its 32 ETH cap
        validator = _validator(32, topups=[_topup(100)])
        # Act
        result = get_predictable_full_inbound_balance(validator)
        # Assert — the excess is still reported here; capping happens downstream
        assert result == Gwei(132 * ETH)


@pytest.mark.unit
class TestGetPredictableInboundBalance:
    """Same sum, clamped to the validator's max effective balance."""

    def test_inbound_balance__topup_stays_below_cap__returns_full_sum(self):
        # Arrange
        validator = _validator(20, topups=[_topup(8)])
        # Act
        result = get_predictable_inbound_balance(validator)
        # Assert
        assert result == Gwei(28 * ETH)

    def test_inbound_balance__eth1_validator_topped_over_cap__clamps_to_32_eth(self):
        # Arrange — 0x01 credentials cap the validator at MIN_ACTIVATION_BALANCE
        validator = _validator(30, topups=[_topup(5)])
        # Act
        result = get_predictable_inbound_balance(validator)
        # Assert
        assert result == MAX_EFFECTIVE_BALANCE

    def test_inbound_balance__compounding_validator_topped_over_32_eth__not_clamped(self):
        # Arrange — the same top-up on 0x02 credentials is fully effective
        validator = _validator(30, compounding=True, topups=[_topup(5)])
        # Act
        result = get_predictable_inbound_balance(validator)
        # Assert
        assert result == Gwei(35 * ETH)

    def test_inbound_balance__compounding_validator_topped_over_electra_cap__clamps_to_2048_eth(self):
        # Arrange — EIP-7251 top-up overshooting the 2048 ETH ceiling
        validator = _validator(2040, compounding=True, topups=[_topup(32)])
        # Act
        result = get_predictable_inbound_balance(validator)
        # Assert
        assert result == MAX_EFFECTIVE_BALANCE_ELECTRA

    def test_inbound_balance__topup_lands_exactly_on_cap__returns_cap(self):
        # Arrange — boundary: sum == cap must not be treated as overflow
        validator = _validator(2016, compounding=True, topups=[_topup(32)])
        # Act
        result = get_predictable_inbound_balance(validator)
        # Assert
        assert result == MAX_EFFECTIVE_BALANCE_ELECTRA


@pytest.mark.unit
class TestGetPredictableInboundSweep:
    """The part of the inbound sum that overflows the cap and will be swept out."""

    def test_inbound_sweep__no_topups_and_balance_below_cap__returns_zero(self):
        # Arrange
        validator = _validator(30)
        # Act
        result = get_predictable_inbound_sweep(validator)
        # Assert
        assert result == Gwei(0)

    def test_inbound_sweep__eth1_validator_topped_over_cap__returns_excess(self):
        # Arrange — 30 + 5 ETH against a 32 ETH cap leaves 3 ETH sweepable
        validator = _validator(30, topups=[_topup(5)])
        # Act
        result = get_predictable_inbound_sweep(validator)
        # Assert
        assert result == Gwei(3 * ETH)

    def test_inbound_sweep__topup_lands_exactly_on_cap__returns_zero(self):
        # Arrange — boundary: nothing overflows when the sum equals the cap
        validator = _validator(24, topups=[_topup(8)])
        # Act
        result = get_predictable_inbound_sweep(validator)
        # Assert
        assert result == Gwei(0)

    def test_inbound_sweep__compounding_validator_topped_over_electra_cap__returns_excess(self):
        # Arrange
        validator = _validator(2040, compounding=True, topups=[_topup(32)])
        # Act
        result = get_predictable_inbound_sweep(validator)
        # Assert
        assert result == Gwei(24 * ETH)

    def test_inbound_sweep__consolidation_pushes_over_cap__counts_toward_excess(self):
        # Arrange — incoming consolidations overflow the cap just like top-ups do
        validator = _validator(30, incoming=[_incoming_consolidation(10)])
        # Act
        result = get_predictable_inbound_sweep(validator)
        # Assert
        assert result == Gwei(8 * ETH)

    def test_inbound_sweep__and_inbound_balance__together_reconstruct_full_balance(self):
        # Arrange — the split must be lossless, whatever the mix of flows
        validator = _validator(30, topups=[_topup(5), _topup(1.5)], incoming=[_incoming_consolidation(2)])
        # Act
        capped = get_predictable_inbound_balance(validator)
        swept = get_predictable_inbound_sweep(validator)
        # Assert
        assert capped + swept == get_predictable_full_inbound_balance(validator)
