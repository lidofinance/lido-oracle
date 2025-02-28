from collections import defaultdict
from unittest.mock import Mock, call, patch

import pytest
from web3.types import Wei

from src.constants import UINT64_MAX
from src.modules.csm.csm import CSOracle
from src.modules.csm.distribution import Distribution, ValidatorDuties
from src.modules.csm.log import FramePerfLog, ValidatorFrameSummary
from src.modules.csm.state import DutyAccumulator, State, Duties
from src.modules.csm.types import StrikesList
from src.providers.execution.contracts.cs_parameters_registry import StrikesParams, PerformanceCoefficients
from src.providers.execution.exceptions import InconsistentData
from src.types import NodeOperatorId
from src.web3py.extensions import CSM
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory


@pytest.fixture()
def module(web3, csm: CSM):
    yield CSOracle(web3)


def test_calculate_distribution_handles_single_frame(module: CSOracle, monkeypatch):
    module.converter = Mock()
    module.state = Mock()
    module.state.frames = [(1, 2)]
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=2)
    last_report = Mock(strikes={}, rewards=[])

    module.w3.csm.fee_distributor.shares_to_distribute = Mock(side_effect=[500])
    module.w3.csm.get_curve_params = Mock(return_value=Mock(strikes_params=StrikesParams(lifetime=6, threshold=Mock())))
    module.w3.lido_validators = Mock(get_module_validators_by_node_operators=Mock(return_value={}))

    monkeypatch.setattr(
        Distribution,
        "_calculate_distribution_in_frame",
        Mock(
            return_value=(
                # rewards
                {
                    NodeOperatorId(1): 500,
                },
                # distributed_rewards
                500,
                # rebate_to_protocol
                0,
                # strikes
                {
                    (NodeOperatorId(0), b"42"): 1,
                    (NodeOperatorId(2), b"17"): 2,
                },
            )
        ),
    )

    distribution = module.calculate_distribution(blockstamp, last_report)

    assert distribution.total_rewards == 500
    assert distribution.total_rewards_map[NodeOperatorId(1)] == 500
    assert distribution.strikes == {
        (NodeOperatorId(0), b"42"): [1, 0, 0, 0, 0, 0],
        (NodeOperatorId(2), b"17"): [2, 0, 0, 0, 0, 0],
    }
    assert len(distribution.logs) == 1


def test_calculate_distribution_handles_multiple_frames(module: CSOracle, monkeypatch):
    module.converter = Mock()
    module.state = Mock()
    module.state.frames = [(1, 2), (3, 4), (5, 6)]
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=2)
    last_report = Mock(strikes={}, rewards=[])

    module.w3.csm.fee_distributor.shares_to_distribute = Mock(side_effect=[500, 1500, 1600])
    module.w3.csm.get_curve_params = Mock(return_value=Mock(strikes_params=StrikesParams(lifetime=6, threshold=Mock())))
    module.w3.lido_validators = Mock(get_module_validators_by_node_operators=Mock(return_value={}))

    monkeypatch.setattr(Distribution, "_get_ref_blockstamp_for_frame", Mock(return_value=blockstamp))
    monkeypatch.setattr(
        Distribution,
        "_calculate_distribution_in_frame",
        Mock(
            side_effect=[
                (
                    # rewards
                    {
                        NodeOperatorId(1): 500,
                    },
                    # distributed_rewards
                    500,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {
                        (NodeOperatorId(0), b"42"): 1,
                        (NodeOperatorId(2), b"17"): 2,
                    },
                ),
                (
                    # rewards
                    {
                        NodeOperatorId(1): 136,
                        NodeOperatorId(3): 777,
                    },
                    # distributed_rewards
                    913,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {
                        (NodeOperatorId(0), b"42"): 3,
                    },
                ),
                (
                    # rewards
                    {
                        NodeOperatorId(1): 164,
                    },
                    # distributed_rewards
                    164,
                    # rebate_to_protocol
                    0,
                    # strikes
                    {
                        (NodeOperatorId(2), b"17"): 4,
                        (NodeOperatorId(2), b"18"): 1,
                    },
                ),
            ]
        ),
    )

    distribution = module.calculate_distribution(blockstamp, last_report)

    assert distribution.total_rewards == 800 + 777
    assert distribution.total_rewards_map[NodeOperatorId(1)] == 800
    assert distribution.total_rewards_map[NodeOperatorId(3)] == 777
    assert distribution.strikes == {
        (NodeOperatorId(0), b"42"): [0, 3, 1, 0, 0, 0],
        (NodeOperatorId(2), b"17"): [4, 0, 2, 0, 0, 0],
        (NodeOperatorId(2), b"18"): [1, 0, 0, 0, 0, 0],
    }
    assert len(distribution.logs) == len(module.state.frames)
    Distribution._get_ref_blockstamp_for_frame.assert_has_calls(
        [call(blockstamp, frame[1]) for frame in module.state.frames[1:]]
    )


def test_calculate_distribution_handles_invalid_distribution(module: CSOracle, monkeypatch):
    module.converter = Mock()
    module.state = Mock()
    module.state.frames = [(1, 2)]
    blockstamp = Mock()
    last_report = Mock(strikes={}, rewards=[])

    module.w3.csm.fee_distributor.shares_to_distribute = Mock(side_effect=[500])
    module.w3.csm.get_curve_params = Mock(return_value=Mock(strikes_params=StrikesParams(lifetime=6, threshold=Mock())))
    module.w3.lido_validators = Mock(get_module_validators_by_node_operators=Mock(return_value={}))
    monkeypatch.setattr(Distribution, "_get_ref_blockstamp_for_frame", Mock(return_value=blockstamp))
    monkeypatch.setattr(
        Distribution,
        "_calculate_distribution_in_frame",
        Mock(
            return_value=(
                # rewards
                {NodeOperatorId(1): 600},
                # distributed_rewards
                500,
                # rebate_to_protocol
                0,
                # strikes
                {},
            )
        ),
    )

    with pytest.raises(InconsistentData, match="Invalid distribution"):
        module.calculate_distribution(blockstamp, last_report)


def test_calculate_distribution_in_frame_handles_no_any_duties(module: CSOracle, monkeypatch):
    frame = (1, 2)
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}

    state = State()
    state.data = {frame: Duties()}
    state.frames = [frame]
    blockstamp = Mock()

    log = FramePerfLog(Mock(), frame)

    distribution = Distribution(module.w3, Mock(), state)
    rewards_distribution, distributed_rewards, rebate_to_protocol, strikes_in_frame = (
        distribution._calculate_distribution_in_frame(
            frame, blockstamp, rewards_to_distribute, operators_to_validators, log
        )
    )

    assert rewards_distribution[node_operator_id] == 0
    assert log.operators[node_operator_id].distributed == 0
    assert log.operators[node_operator_id].validators == defaultdict(ValidatorFrameSummary)
    assert not strikes_in_frame


def test_calculate_distribution_in_frame_handles_above_threshold_performance(module: CSOracle):
    frame = Mock()
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    state = State()
    attestation_duty = DutyAccumulator(assigned=10, included=6)
    proposal_duty = DutyAccumulator(assigned=10, included=6)
    sync_duty = DutyAccumulator(assigned=10, included=6)
    state.data = {
        frame: Duties(
            attestations={validator.index: attestation_duty},
            proposals={validator.index: proposal_duty},
            syncs={validator.index: sync_duty},
        )
    }
    state.frames = [frame]
    blockstamp = Mock()

    log = FramePerfLog(Mock(), frame)

    module.w3.csm.get_curve_params = Mock(
        return_value=Mock(
            strikes_params=StrikesParams(lifetime=6, threshold=Mock()),
            perf_leeway_data=Mock(get_for=Mock(return_value=0.1)),
            reward_share_data=Mock(get_for=Mock(return_value=1)),
            perf_coeffs=PerformanceCoefficients(),
        )
    )

    distribution = Distribution(module.w3, Mock(), state)
    rewards_distribution, distributed_rewards, rebate_to_protocol, strikes_in_frame = (
        distribution._calculate_distribution_in_frame(
            frame, blockstamp, rewards_to_distribute, operators_to_validators, log
        )
    )

    assert distributed_rewards > 0
    assert rebate_to_protocol == 0
    assert rewards_distribution[node_operator_id] > 0  # no need to check exact value
    assert log.operators[node_operator_id].distributed > 0
    assert log.operators[node_operator_id].validators[validator.index].attestation_duty == attestation_duty
    assert log.operators[node_operator_id].validators[validator.index].proposal_duty == proposal_duty
    assert log.operators[node_operator_id].validators[validator.index].sync_duty == sync_duty
    assert not strikes_in_frame


def test_calculate_distribution_in_frame_handles_below_threshold_performance(module: CSOracle):
    frame = Mock()
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    state = State()
    attestation_duty = DutyAccumulator(assigned=10, included=5)
    proposal_duty = DutyAccumulator(assigned=10, included=5)
    sync_duty = DutyAccumulator(assigned=10, included=5)
    state.data = {
        frame: Duties(
            attestations={validator.index: attestation_duty},
            proposals={validator.index: proposal_duty},
            syncs={validator.index: sync_duty},
        )
    }
    state.frames = [frame]
    blockstamp = Mock()

    log = FramePerfLog(Mock(), frame)

    module.w3.csm.get_curve_params = Mock(
        return_value=Mock(
            strikes_params=StrikesParams(lifetime=6, threshold=Mock()),
            perf_leeway_data=Mock(get_for=Mock(return_value=-0.1)),
            reward_share_data=Mock(get_for=Mock(return_value=1)),
            perf_coeffs=PerformanceCoefficients(),
        )
    )

    distribution = Distribution(module.w3, Mock(), state)
    rewards_distribution, distributed_rewards, rebate_to_protocol, strikes_in_frame = (
        distribution._calculate_distribution_in_frame(
            frame, blockstamp, rewards_to_distribute, operators_to_validators, log
        )
    )

    assert rewards_distribution[node_operator_id] == 0
    assert log.operators[node_operator_id].distributed == 0
    assert log.operators[node_operator_id].validators[validator.index].attestation_duty == attestation_duty
    assert log.operators[node_operator_id].validators[validator.index].proposal_duty == proposal_duty
    assert log.operators[node_operator_id].validators[validator.index].sync_duty == sync_duty
    assert (node_operator_id, validator.pubkey) in strikes_in_frame


def test_process_validator_duty_handles_above_threshold_performance():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    threshold = 0.5
    reward_share = 1

    validator_duties = ValidatorDuties(
        attestation=DutyAccumulator(assigned=10, included=6),
        proposal=DutyAccumulator(assigned=10, included=6),
        sync=DutyAccumulator(assigned=10, included=6),
    )

    outcome = Distribution.get_validator_duties_outcome(
        validator,
        validator_duties,
        threshold,
        reward_share,
        PerformanceCoefficients(),
        log_operator,
    )

    assert outcome.strikes == 0
    assert outcome.rebate_share == 0
    assert outcome.participation_share == 10
    assert log_operator.validators[validator.index].attestation_duty == validator_duties.attestation
    assert log_operator.validators[validator.index].proposal_duty == validator_duties.proposal
    assert log_operator.validators[validator.index].sync_duty == validator_duties.sync


def test_process_validator_duty_handles_below_threshold_performance():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    threshold = 0.5
    reward_share = 1

    validator_duties = ValidatorDuties(
        attestation=DutyAccumulator(assigned=10, included=4),
        proposal=DutyAccumulator(assigned=10, included=4),
        sync=DutyAccumulator(assigned=10, included=4),
    )

    outcome = Distribution.get_validator_duties_outcome(
        validator,
        validator_duties,
        threshold,
        reward_share,
        PerformanceCoefficients(),
        log_operator,
    )

    assert outcome.strikes == 1
    assert outcome.rebate_share == 0
    assert outcome.participation_share == 0
    assert log_operator.validators[validator.index].attestation_duty == validator_duties.attestation
    assert log_operator.validators[validator.index].proposal_duty == validator_duties.proposal
    assert log_operator.validators[validator.index].sync_duty == validator_duties.sync


def test_process_validator_duty_handles_no_duty_assigned():
    validator = LidoValidatorFactory.build()
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    threshold = 0.5
    reward_share = 1

    validator_duties = ValidatorDuties(attestation=None, proposal=None, sync=None)

    outcome = Distribution.get_validator_duties_outcome(
        validator,
        validator_duties,
        threshold,
        reward_share,
        PerformanceCoefficients(),
        log_operator,
    )

    assert outcome.strikes == 0
    assert outcome.rebate_share == 0
    assert outcome.participation_share == 0
    assert validator.index not in log_operator.validators


def test_process_validator_duty_handles_slashed_validator():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = True
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    threshold = 0.5
    reward_share = 1

    validator_duties = ValidatorDuties(
        attestation=DutyAccumulator(assigned=1, included=1),
        proposal=DutyAccumulator(assigned=1, included=1),
        sync=DutyAccumulator(assigned=1, included=1),
    )

    outcome = Distribution.get_validator_duties_outcome(
        validator,
        validator_duties,
        threshold,
        reward_share,
        PerformanceCoefficients(),
        log_operator,
    )

    assert outcome.strikes == 1
    assert outcome.rebate_share == 0
    assert outcome.participation_share == 0
    assert log_operator.validators[validator.index].slashed is True


def test_calc_rewards_distribution_in_frame_correctly_distributes_rewards():
    participation_shares = {NodeOperatorId(1): 100, NodeOperatorId(2): 200}
    rewards_to_distribute = Wei(1 * 10**18)
    rebate_share = 0

    rewards_distribution = Distribution.calc_rewards_distribution_in_frame(
        participation_shares, rebate_share, rewards_to_distribute
    )

    assert rewards_distribution[NodeOperatorId(1)] == Wei(333333333333333333)
    assert rewards_distribution[NodeOperatorId(2)] == Wei(666666666666666666)


def test_calc_rewards_distribution_in_frame_handles_zero_participation():
    participation_shares = {NodeOperatorId(1): 0, NodeOperatorId(2): 0}
    rewards_to_distribute = Wei(1 * 10**18)
    rebate_share = 0

    rewards_distribution = Distribution.calc_rewards_distribution_in_frame(
        participation_shares, rebate_share, rewards_to_distribute
    )

    assert rewards_distribution[NodeOperatorId(1)] == 0
    assert rewards_distribution[NodeOperatorId(2)] == 0


def test_calc_rewards_distribution_in_frame_handles_no_participation():
    participation_shares = {}
    rewards_to_distribute = Wei(1 * 10**18)
    rebate_share = 0

    rewards_distribution = Distribution.calc_rewards_distribution_in_frame(
        participation_shares, rebate_share, rewards_to_distribute
    )

    assert len(rewards_distribution) == 0


def test_calc_rewards_distribution_in_frame_handles_partial_participation():
    participation_shares = {NodeOperatorId(1): 100, NodeOperatorId(2): 0}
    rewards_to_distribute = Wei(1 * 10**18)
    rebate_share = 0

    rewards_distribution = Distribution.calc_rewards_distribution_in_frame(
        participation_shares, rebate_share, rewards_to_distribute
    )

    assert rewards_distribution[NodeOperatorId(1)] == Wei(1 * 10**18)
    assert rewards_distribution[NodeOperatorId(2)] == 0


def test_calc_rewards_distribution_in_frame_handles_negative_to_distribute():
    participation_shares = {NodeOperatorId(1): 100, NodeOperatorId(2): 200}
    rewards_to_distribute = Wei(-1)
    rebate_share = 0

    with pytest.raises(ValueError, match="Invalid rewards to distribute"):
        Distribution.calc_rewards_distribution_in_frame(participation_shares, rebate_share, rewards_to_distribute)


@pytest.mark.parametrize(
    ("acc", "strikes_in_frame", "threshold_per_op", "expected"),
    [
        pytest.param({}, {}, {}, {}, id="empty_acc_empty_strikes_in_frame"),
        pytest.param(
            {},
            {
                (NodeOperatorId(42), b"00"): 3,
                (NodeOperatorId(17), b"01"): 1,
            },
            {
                NodeOperatorId(42): Mock(lifetime=6),
                NodeOperatorId(17): Mock(lifetime=4),
            },
            {
                (NodeOperatorId(42), b"00"): [3, 0, 0, 0, 0, 0],
                (NodeOperatorId(17), b"01"): [1, 0, 0, 0],
            },
            id="empty_acc_non_empty_strikes_in_frame",
        ),
        pytest.param(
            {
                (NodeOperatorId(42), b"00"): StrikesList([3, 0, 0, 0, 0, 0]),
                (NodeOperatorId(17), b"01"): StrikesList([1, 0, 0, 0]),
            },
            {},
            {
                NodeOperatorId(42): Mock(lifetime=5),
                NodeOperatorId(17): Mock(lifetime=4),
            },
            {
                (NodeOperatorId(42), b"00"): [0, 3, 0, 0, 0],
                (NodeOperatorId(17), b"01"): [0, 1, 0, 0],
            },
            id="non_empty_acc_empty_strikes_in_frame",
        ),
        pytest.param(
            {
                (NodeOperatorId(42), b"00"): StrikesList([3, 0, 0, 0, 0, 0]),
                (NodeOperatorId(17), b"01"): StrikesList([1, 0, 0, 0]),
            },
            {
                (NodeOperatorId(42), b"00"): 2,
                (NodeOperatorId(18), b"02"): 1,
            },
            {
                NodeOperatorId(42): Mock(lifetime=5),
                NodeOperatorId(17): Mock(lifetime=4),
                NodeOperatorId(18): Mock(lifetime=6),
            },
            {
                (NodeOperatorId(42), b"00"): [2, 3, 0, 0, 0],
                (NodeOperatorId(17), b"01"): [0, 1, 0, 0],
                (NodeOperatorId(18), b"02"): [1, 0, 0, 0, 0, 0],
            },
            id="non_empty_acc_non_empty_strikes_in_frame",
        ),
    ],
)
def test_merge_strikes(
    module: CSOracle,
    acc: dict,
    strikes_in_frame: dict,
    threshold_per_op: dict,
    expected: dict,
):
    distribution = Distribution(module.w3, Mock(), Mock())
    distribution.w3.csm.get_curve_params = Mock(
        side_effect=lambda no_id, _: Mock(strikes_params=threshold_per_op[no_id])
    )

    distribution._merge_strikes(acc, strikes_in_frame, frame_blockstamp=Mock())

    assert acc == expected
