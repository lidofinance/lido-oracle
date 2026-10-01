import math
from collections import defaultdict
from unittest.mock import Mock, call, patch

import pytest
from web3.types import Wei

from src.constants import EFFECTIVE_BALANCE_INCREMENT, MIN_ACTIVATION_BALANCE
from src.modules.oracles.staking_modules.common.distribution import Distribution
from src.modules.oracles.staking_modules.common.log import FramePerfLog
from src.modules.oracles.staking_modules.common.state import DutyAccumulator, NetworkDuties, State
from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from src.modules.oracles.staking_modules.community_staking_0x02.csm_0x02 import CSM0x02PerformanceOracle
from src.modules.oracles.staking_modules.curated.cm import CMPerformanceOracle
from src.providers.execution.contracts.cs_parameters_registry import (
    KeyNumberValueInterval,
)
from src.types import EpochNumber, NodeOperatorId
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.curated import (
    ASSIGNED_ATTESTATIONS,
    FULL_SHARE,
    HASH_A,
    HASH_B,
    NO_ID,
    make_active_validator,
    make_curve_params,
)


@pytest.mark.unit
class TestDistributionWithFeeDiscounts:
    frame = (EpochNumber(0), EpochNumber(31))

    def make_distribution(self, curve_params: dict, discounts: dict, validators: list):
        w3 = Mock()
        w3.staking_module.get_curve_params.side_effect = lambda no_id, _: curve_params[no_id]
        w3.staking_module.get_fee_share_discount.side_effect = lambda no_id, _: discounts[no_id]
        state = State(*self.frame, epochs_per_frame=32)
        state.data = {
            self.frame: NetworkDuties(
                attestations=defaultdict(
                    DutyAccumulator,
                    {
                        v.index: DutyAccumulator(assigned=ASSIGNED_ATTESTATIONS, included=ASSIGNED_ATTESTATIONS)
                        for v in validators
                    },
                ),
                proposals=defaultdict(DutyAccumulator),
                syncs=defaultdict(DutyAccumulator),
            )
        }
        distribution = Distribution(w3, converter=Mock(), state=state)
        distribution._get_network_performance = Mock(return_value=1.0)
        return distribution

    @pytest.mark.parametrize(
        "discount, expected_reward_share, expected_participation",
        [
            (0, 1.0, FULL_SHARE),
            (100, 0.99, math.ceil(FULL_SHARE * 0.99)),
            (5000, 0.5, FULL_SHARE // 2),
            (10000, 0.0, 0),
        ],
    )
    def test_calculate_distribution_in_frame__discount_applied__scales_operator_reward_share(
        self, discount, expected_reward_share, expected_participation
    ):
        validator = make_active_validator(1)
        distribution = self.make_distribution(
            {NO_ID: make_curve_params([KeyNumberValueInterval(1, 10000)])}, {NO_ID: discount}, [validator]
        )
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        log = FramePerfLog(blockstamp, self.frame)

        rewards, distributed, rebate, _ = distribution._calculate_distribution_in_frame(
            self.frame, blockstamp, Wei(FULL_SHARE), {NO_ID: [validator]}, log
        )

        assert distributed == expected_participation
        assert rebate == FULL_SHARE - expected_participation
        assert dict(rewards) == ({NO_ID: expected_participation} if expected_participation else {})
        assert log.operators[NO_ID].validators[validator.index].reward_share == pytest.approx(expected_reward_share)

    def test_calculate_distribution_in_frame__zero_discount__keeps_float_reward_share(self):
        validator = make_active_validator(1)
        distribution = self.make_distribution(
            {NO_ID: make_curve_params([KeyNumberValueInterval(1, 8500)])}, {NO_ID: 0}, [validator]
        )
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        log = FramePerfLog(blockstamp, self.frame)

        distribution._calculate_distribution_in_frame(
            self.frame, blockstamp, Wei(FULL_SHARE), {NO_ID: [validator]}, log
        )

        reward_share = log.operators[NO_ID].validators[validator.index].reward_share
        assert type(reward_share) is float
        assert reward_share == 0.85

    def test_calculate_distribution_in_frame__distinct_curves_and_key_intervals__applies_per_operator_and_key(self):
        other_no_id = NodeOperatorId(8)
        v_first = make_active_validator(1, balance_multiplier=2)
        v_second = make_active_validator(2)
        v_other = make_active_validator(3)
        distribution = self.make_distribution(
            {
                NO_ID: make_curve_params([KeyNumberValueInterval(1, 10000), KeyNumberValueInterval(2, 5000)]),
                other_no_id: make_curve_params([KeyNumberValueInterval(1, 7000)]),
            },
            {NO_ID: 5000, other_no_id: 2000},
            [v_first, v_second, v_other],
        )
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        log = FramePerfLog(blockstamp, self.frame)

        distribution._calculate_distribution_in_frame(
            self.frame, blockstamp, Wei(1000), {NO_ID: [v_second, v_first], other_no_id: [v_other]}, log
        )

        assert log.operators[NO_ID].validators[v_first.index].reward_share == 0.5
        assert log.operators[NO_ID].validators[v_second.index].reward_share == 0.25
        assert log.operators[other_no_id].validators[v_other.index].reward_share == pytest.approx(0.56)

    def test_calculate_distribution_in_frame__several_validators__resolves_discount_once_per_operator(self):
        validators = [make_active_validator(i) for i in (1, 2, 3)]
        distribution = self.make_distribution(
            {NO_ID: make_curve_params([KeyNumberValueInterval(1, 10000)])}, {NO_ID: 100}, validators
        )
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        log = FramePerfLog(blockstamp, self.frame)

        distribution._calculate_distribution_in_frame(self.frame, blockstamp, Wei(1000), {NO_ID: validators}, log)

        distribution.w3.staking_module.get_fee_share_discount.assert_called_once_with(NO_ID, blockstamp)

    def test_calculate_distribution_in_frame__operator_without_active_validators__does_not_resolve_discount(self):
        validator = make_active_validator(1)
        distribution = self.make_distribution(
            {NO_ID: make_curve_params([KeyNumberValueInterval(1, 10000)])}, {NO_ID: 100}, []
        )
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        log = FramePerfLog(blockstamp, self.frame)

        distribution._calculate_distribution_in_frame(self.frame, blockstamp, Wei(1000), {NO_ID: [validator]}, log)

        distribution.w3.staking_module.get_fee_share_discount.assert_not_called()


@pytest.mark.unit
class TestDistributionCalculateWithFeeDiscounts:
    def test_calculate__two_frames__resolves_discount_once_per_operator_with_each_frame_blockstamp(self):
        frame_1 = (EpochNumber(0), EpochNumber(31))
        frame_2 = (EpochNumber(32), EpochNumber(63))
        blockstamp_1 = ReferenceBlockStampFactory.build(block_hash=HASH_A, ref_epoch=31)
        blockstamp_2 = ReferenceBlockStampFactory.build(block_hash=HASH_B, ref_epoch=63)
        validators = [make_active_validator(i) for i in (1, 2)]
        w3 = Mock()
        w3.staking_module.fee_distributor.shares_to_distribute.side_effect = lambda block_hash: (
            1000 if block_hash == HASH_A else 2000
        )
        w3.staking_module.get_curve_params.return_value = make_curve_params([KeyNumberValueInterval(1, 10000)])
        w3.staking_module.get_fee_share_discount.return_value = 0
        state = State(frame_1[0], frame_2[1], epochs_per_frame=32)
        state.data = {
            frame: NetworkDuties(
                attestations=defaultdict(
                    DutyAccumulator,
                    {v.index: DutyAccumulator(ASSIGNED_ATTESTATIONS, ASSIGNED_ATTESTATIONS) for v in validators},
                ),
                proposals=defaultdict(DutyAccumulator),
                syncs=defaultdict(DutyAccumulator),
            )
            for frame in (frame_1, frame_2)
        }
        distribution = Distribution(w3, converter=Mock(), state=state)
        distribution._get_module_validators = Mock(return_value={NO_ID: validators})
        distribution._get_network_performance = Mock(return_value=1.0)

        with patch(
            "src.modules.oracles.staking_modules.common.distribution.get_reference_blockstamp",
            return_value=blockstamp_1,
        ):
            distribution.calculate(blockstamp_2, Mock(strikes={}, rewards=[]))

        assert w3.staking_module.get_fee_share_discount.call_args_list == [
            call(NO_ID, blockstamp_1),
            call(NO_ID, blockstamp_2),
        ]


@pytest.mark.unit
class TestDistributionDiscountedShare:
    frame = (EpochNumber(0), EpochNumber(31))

    def build_distribution(self, base_bp: int, assigned: int, discount: int, validator) -> Distribution:
        state = State(*self.frame, epochs_per_frame=32)
        state.data = {
            self.frame: NetworkDuties(
                attestations=defaultdict(DutyAccumulator, {validator.index: DutyAccumulator(assigned, assigned)}),
                proposals=defaultdict(DutyAccumulator),
                syncs=defaultdict(DutyAccumulator),
            )
        }
        w3 = Mock()
        w3.staking_module.get_curve_params.return_value = make_curve_params([KeyNumberValueInterval(1, base_bp)])
        w3.staking_module.get_fee_share_discount.return_value = discount
        distribution = Distribution(w3, converter=Mock(), state=state)
        distribution._get_network_performance = Mock(return_value=1.0)
        return distribution

    def test_calculate_distribution_in_frame__discount_applied__participation_is_float_ceil_of_effective_share(self):
        base_bp, discount, assigned = 6250, 1200, 100
        validator = make_active_validator(1)
        distribution = self.build_distribution(base_bp, assigned, discount, validator)
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        log = FramePerfLog(blockstamp, self.frame)
        effective_assigned = assigned * MIN_ACTIVATION_BALANCE // EFFECTIVE_BALANCE_INCREMENT
        expected_share = 0.625 * ((10000 - 1200) / 10000)

        _, distributed, rebate, _ = distribution._calculate_distribution_in_frame(
            self.frame, blockstamp, Wei(effective_assigned), {NO_ID: [validator]}, log
        )

        assert effective_assigned == 3200
        assert distributed == math.ceil(effective_assigned * expected_share) == 1761
        assert rebate == effective_assigned - 1761
        assert log.operators[NO_ID].validators[validator.index].reward_share == expected_share

    @pytest.mark.parametrize("base_bp", [0, 1, 102, 6250, 8500, 9999, 10000])
    @pytest.mark.parametrize("assigned", [1, 7, 100, 625])
    def test_calculate_distribution_in_frame__zero_discount__matches_undiscounted_share(self, base_bp, assigned):
        validator = make_active_validator(1)
        blockstamp = ReferenceBlockStampFactory.build(ref_epoch=31)
        effective_assigned = assigned * MIN_ACTIVATION_BALANCE // EFFECTIVE_BALANCE_INCREMENT
        base_share = base_bp / 10000
        distribution = self.build_distribution(base_bp, assigned, 0, validator)
        log = FramePerfLog(blockstamp, self.frame)

        _, distributed, rebate, _ = distribution._calculate_distribution_in_frame(
            self.frame, blockstamp, Wei(effective_assigned), {NO_ID: [validator]}, log
        )

        assert distributed == math.ceil(effective_assigned * base_share)
        assert rebate == effective_assigned - distributed
        assert log.operators[NO_ID].validators[validator.index].reward_share == base_share

    @pytest.mark.parametrize("base_share", [0.0, 0.3334, 0.5834, 0.625, 0.875, 1.0])
    @pytest.mark.parametrize("discount", [0, 100, 1200, 5000, 10000])
    def test_calc_discounted_reward_share__base_and_discount__bit_identical_to_reference_expression(
        self, base_share, discount
    ):
        result = Distribution.calc_discounted_reward_share(base_share, discount)

        assert result.hex() == (base_share * ((10000 - discount) / 10000)).hex()

    @pytest.mark.parametrize("base_share", [0.0, 0.3334, 0.5834, 0.625, 0.875, 1.0])
    def test_calc_discounted_reward_share__zero_discount__returns_identical_float(self, base_share):
        result = Distribution.calc_discounted_reward_share(base_share, 0)

        assert result.hex() == base_share.hex()


@pytest.mark.unit
class TestCMPerformanceOracleConfig:
    def test_class_attributes__cm_oracle__consensus_version_five(self):
        assert CMPerformanceOracle.COMPATIBLE_CONSENSUS_VERSION == 5

    def test_class_attributes__csm_oracles__consensus_version_four(self):
        for oracle in (CSPerformanceOracle, CSM0x02PerformanceOracle):
            assert oracle.COMPATIBLE_CONSENSUS_VERSION == 4
