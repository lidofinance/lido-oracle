"""EJ-04 — correctness of the Gloas sweep-delay against the EIP-7002 manipulation attack.

Priority is CORRECTNESS, not well-formedness. These scenarios run the *real* sweep functions on a
*real* ``BeaconStateView`` (nothing under test is mocked) and assert the result against an
**independently hand-derived** expectation. Each scenario also carries a pre-fork **attack control**
that proves the manipulation vector genuinely existed and that the Gloas path closes it.

The attack (see ``docs/glamsterdam-oracle-changes.md`` §3): ``pending_partial_withdrawals`` is an
EIP-7002 queue any Ethereum user can flood cheaply. If the sweep-delay projection counts it, a
flood inflates the projected delay → inflates ``predictable_el_balance`` → the ejector requests
*fewer* exits → the withdrawal vault is left underfunded. The fix excludes the partials queue from
the Gloas projection, so the flood cannot move the number.
"""

import pytest

from src.constants import FAR_FUTURE_EPOCH, MIN_ACTIVATION_BALANCE
from src.modules.common.types import ChainConfig
from src.modules.oracles.ejector.sweep import (
    get_sweep_delay_in_epochs,
    predict_withdrawals_number_in_sweep_cycle,
)
from src.providers.consensus.types import BeaconStateView, PendingPartialWithdrawal
from src.types import EpochNumber, Gwei, SlotNumber, ValidatorIndex
from tests.factory.configs import ChainConfigFactory
from tests.factory.consensus import BeaconStateViewFactory
from tests.factory.no_registry import ValidatorStateFactory


# A single partial-withdrawal-source validator sits at index 0; the fully-withdrawable sweep
# targets follow it. Keeping the two groups disjoint means the partials flood cannot perturb the
# validator-sweep count, so the independent expectation stays exact.
_PARTIAL_SOURCE_INDEX = ValidatorIndex(0)
_PARTIAL_SOURCE_BALANCE = Gwei(MIN_ACTIVATION_BALANCE + 8 * 10**9)


def _fully_withdrawable_validator() -> object:
    """0x01, exactly at MIN_ACTIVATION_BALANCE, already withdrawable: contributes exactly one full
    (not partial) validator withdrawal to the sweep."""
    return ValidatorStateFactory.build(
        withdrawal_credentials="0x01",
        effective_balance=MIN_ACTIVATION_BALANCE,
        withdrawable_epoch=0,
    )


def _partial_source_validator() -> object:
    """0x02 with effective != max and balance < max: passes the EIP-7002 partials filter
    (exit_epoch FAR_FUTURE, effective >= MIN_ACTIVATION, balance > MIN_ACTIVATION) yet is itself
    neither fully- nor partially-withdrawable, so it never enters the validator-sweep count."""
    return ValidatorStateFactory.build(
        withdrawal_credentials="0x02",
        effective_balance=Gwei(MIN_ACTIVATION_BALANCE + 10**9),
        exit_epoch=FAR_FUTURE_EPOCH,
        withdrawable_epoch=FAR_FUTURE_EPOCH,
    )


def _state(num_fully_withdrawable: int, num_pending_partials: int) -> BeaconStateView:
    validators = [_partial_source_validator()] + [_fully_withdrawable_validator()] * num_fully_withdrawable
    balances = [_PARTIAL_SOURCE_BALANCE] + [MIN_ACTIVATION_BALANCE] * num_fully_withdrawable
    partials = [
        PendingPartialWithdrawal(
            validator_index=_PARTIAL_SOURCE_INDEX, amount=Gwei(1), withdrawable_epoch=EpochNumber(0)
        )
    ] * num_pending_partials
    return BeaconStateViewFactory.build(
        slot=SlotNumber(32),
        validators=validators,
        balances=balances,
        pending_partial_withdrawals=partials,
        slashings=[],
    )


@pytest.fixture()
def spec() -> ChainConfig:
    return ChainConfigFactory.build()  # slots_per_epoch = 32


@pytest.mark.unit
@pytest.mark.scenario
class TestSweepDelayManipulation:
    def test_predict_number__gloas_ignores_partials_flood__matches_independent_count(self, spec: ChainConfig) -> None:
        # Arrange: 3 fully-withdrawable validators; flood the partials queue with 0, 5, 100 entries.
        # Independent ground truth:
        #   ratio = MAX_PENDING_PARTIALS / (MAX_WITHDRAWALS_PER_PAYLOAD - MAX_PENDING_PARTIALS) = 8/8 = 1
        #   gloas  = validator_withdrawals                        = 3       (partials excluded)
        #   legacy = validator_withdrawals + min(P, ceil(3 * 1))  = 3 + min(P, 3)
        num_fully_withdrawable = 3
        floods = [0, 5, 100]

        # Act
        gloas = [
            predict_withdrawals_number_in_sweep_cycle(_state(num_fully_withdrawable, p), spec.slots_per_epoch, True)
            for p in floods
        ]
        legacy = [
            predict_withdrawals_number_in_sweep_cycle(_state(num_fully_withdrawable, p), spec.slots_per_epoch, False)
            for p in floods
        ]

        # Assert — exact independent ground truth.
        assert gloas == [3, 3, 3], "Gloas count must equal the validator-sweep count regardless of partials"
        assert legacy == [3, 6, 6], "legacy count must grow with the partials flood (then saturate at 2*V)"

        # Non-manipulability vs. attack control on the same states.
        assert len(set(gloas)) == 1, "a partials flood must not move the Gloas number (non-manipulable)"
        assert legacy[1] > legacy[0], "the pre-fork path was manipulable — the flood inflated the number"

    def test_sweep_delay__partial_flood_cannot_inflate_gloas_delay__fund_safe_direction(
        self, spec: ChainConfig
    ) -> None:
        # Arrange: 1024 fully-withdrawable validators, flooded with 2048 partials.
        # Independent ground truth (delay = ceil(n / 16 / 32) // 2):
        #   gloas  n = 1024  -> ceil(1024/512)//2 = 2//2 = 1
        #   legacy n = 2048  -> ceil(2048/512)//2 = 4//2 = 2
        num_fully_withdrawable, flood = 1024, 2048
        flooded = _state(num_fully_withdrawable, flood)

        # Act
        gloas_delay = get_sweep_delay_in_epochs(flooded, spec, is_gloas_active=True)
        legacy_delay = get_sweep_delay_in_epochs(flooded, spec, is_gloas_active=False)
        gloas_delay_no_flood = get_sweep_delay_in_epochs(_state(num_fully_withdrawable, 0), spec, is_gloas_active=True)

        # Assert — exact independent ground truth.
        assert gloas_delay == 1
        assert legacy_delay == 2

        # Non-manipulability: the flood does not change the Gloas delay at all.
        assert gloas_delay == gloas_delay_no_flood

        # Fund-safety direction: a longer (manipulated) delay projects more future rewards and makes
        # the ejector request FEWER exits. The Gloas delay is <= the manipulable one, so the ejector
        # can only be pushed toward *more* exits — it can never be tricked into under-ejecting.
        assert gloas_delay < legacy_delay
