from collections import defaultdict
from unittest.mock import Mock, call

import pytest
from web3.types import Wei

from src.constants import UINT64_MAX
from src.modules.csm.csm import CSMError, CSOracle
from src.modules.csm.log import FramePerfLog, ValidatorFrameSummary
from src.modules.csm.state import AttestationsAccumulator, State
from src.modules.csm.types import StrikesList
from src.providers.execution.contracts.cs_parameters_registry import StrikesParams
from src.types import NodeOperatorId, ValidatorIndex
from src.web3py.extensions import CSM
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory


@pytest.fixture(autouse=True)
def mock_get_staking_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CSOracle, "_get_staking_module", Mock())


@pytest.fixture()
def module(web3, csm: CSM):
    yield CSOracle(web3)


def test_calculate_distribution_handles_single_frame(module: CSOracle):
    module.state = Mock()
    module.state.frames = [(1, 2)]
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=2)
    last_report = Mock(strikes={}, rewards=[])
    module.module_validators_by_node_operators = Mock()
    module._get_performance_threshold = Mock(return_value=1)
    module.w3.csm.fee_distributor.shares_to_distribute = Mock(side_effect=[500])
    module.w3.csm.get_strikes_params = Mock(return_value=StrikesParams(lifetime=6, threshold=Mock()))
    module._calculate_distribution_in_frame = Mock(
        return_value=(
            # rewards
            {
                NodeOperatorId(1): 500,
            },
            # strikes
            {
                (NodeOperatorId(0), b"42"): 1,
                (NodeOperatorId(2), b"17"): 2,
            },
        )
    )

    (
        total_distributed,
        total_rewards,
        strikes,
        logs,
    ) = module.calculate_distribution(blockstamp, last_report)

    assert total_distributed == 500
    assert total_rewards[NodeOperatorId(1)] == 500
    assert strikes == {
        (NodeOperatorId(0), b"42"): [1, 0, 0, 0, 0, 0],
        (NodeOperatorId(2), b"17"): [2, 0, 0, 0, 0, 0],
    }
    assert len(logs) == 1


def test_calculate_distribution_handles_multiple_frames(module: CSOracle):
    module.state = Mock()
    module.state.frames = [(1, 2), (3, 4), (5, 6)]
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=2)
    last_report = Mock(strikes={}, rewards=[])
    module.module_validators_by_node_operators = Mock()
    module._get_ref_blockstamp_for_frame = Mock(return_value=blockstamp)
    module._get_performance_threshold = Mock(return_value=1)
    module.w3.csm.fee_distributor.shares_to_distribute = Mock(side_effect=[500, 1500, 1600])
    module.w3.csm.get_strikes_params = Mock(return_value=StrikesParams(lifetime=6, threshold=Mock()))
    module._calculate_distribution_in_frame = Mock(
        side_effect=[
            (
                # rewards
                {
                    NodeOperatorId(1): 500,
                },
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
                # strikes
                {
                    (NodeOperatorId(2), b"17"): 4,
                    (NodeOperatorId(2), b"18"): 1,
                },
            ),
        ]
    )

    (
        total_distributed,
        total_rewards,
        strikes,
        logs,
    ) = module.calculate_distribution(blockstamp, last_report)

    assert total_distributed == 800 + 777
    assert total_rewards[NodeOperatorId(1)] == 800
    assert total_rewards[NodeOperatorId(3)] == 777
    assert strikes == {
        (NodeOperatorId(0), b"42"): [0, 3, 1, 0, 0, 0],
        (NodeOperatorId(2), b"17"): [4, 0, 2, 0, 0, 0],
        (NodeOperatorId(2), b"18"): [1, 0, 0, 0, 0, 0],
    }
    assert len(logs) == len(module.state.frames)
    module._get_ref_blockstamp_for_frame.assert_has_calls(
        [call(blockstamp, frame[1]) for frame in module.state.frames[1:]]
    )


def test_calculate_distribution_handles_invalid_distribution(module: CSOracle):
    module.state = Mock()
    module.state.frames = [(1, 2)]
    blockstamp = Mock()
    last_report = Mock(strikes={}, rewards=[])
    module.module_validators_by_node_operators = Mock()
    module._get_ref_blockstamp_for_frame = Mock(return_value=blockstamp)
    module._get_performance_threshold = Mock(return_value=1)
    module.w3.csm.fee_distributor.shares_to_distribute = Mock(return_value=500)
    module._calculate_distribution_in_frame = Mock(return_value=({NodeOperatorId(1): 600}, {}))

    with pytest.raises(CSMError, match="Invalid distribution"):
        module.calculate_distribution(blockstamp, last_report)


def test_calculate_distribution_in_frame_handles_no_attestation_duty(module: CSOracle):
    frame = Mock()
    threshold = 1.0
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    module.state = State()
    module.state.data = {frame: defaultdict(AttestationsAccumulator)}
    log = FramePerfLog(Mock(), frame)

    rewards_distribution, strikes_in_frame = module._calculate_distribution_in_frame(
        frame, threshold, rewards_to_distribute, operators_to_validators, log
    )

    assert rewards_distribution[node_operator_id] == 0
    assert log.operators[node_operator_id].distributed == 0
    assert log.operators[node_operator_id].validators == defaultdict(ValidatorFrameSummary)
    assert not strikes_in_frame


def test_calculate_distribution_in_frame_handles_above_threshold_performance(module: CSOracle):
    frame = Mock()
    threshold = 0.5
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    module.state = State()
    attestation_duty = AttestationsAccumulator(assigned=10, included=6)
    module.state.data = {frame: {validator.index: attestation_duty}}
    log = FramePerfLog(Mock(), frame)

    rewards_distribution, strikes_in_frame = module._calculate_distribution_in_frame(
        frame, threshold, rewards_to_distribute, operators_to_validators, log
    )

    assert rewards_distribution[node_operator_id] > 0  # no need to check exact value
    assert log.operators[node_operator_id].distributed > 0
    assert log.operators[node_operator_id].validators[validator.index].attestation_duty == attestation_duty
    assert not strikes_in_frame


def test_calculate_distribution_in_frame_handles_below_threshold_performance(module: CSOracle):
    frame = Mock()
    threshold = 0.5
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    module.state = State()
    attestation_duty = AttestationsAccumulator(assigned=10, included=5)
    module.state.data = {frame: {validator.index: attestation_duty}}
    module._get_performance_threshold = Mock(return_value=0.5)
    log = FramePerfLog(Mock(), frame)

    rewards_distribution, strikes_in_frame = module._calculate_distribution_in_frame(
        frame, threshold, rewards_to_distribute, operators_to_validators, log
    )

    assert rewards_distribution[node_operator_id] == 0
    assert log.operators[node_operator_id].distributed == 0
    assert log.operators[node_operator_id].validators[validator.index].attestation_duty == attestation_duty
    assert (node_operator_id, validator.pubkey) in strikes_in_frame


def test_performance_threshold_calculates_correctly(module):
    state = State()
    state.data = {
        (0, 31): {
            ValidatorIndex(1): AttestationsAccumulator(10, 10),
            ValidatorIndex(2): AttestationsAccumulator(10, 10),
        },
    }
    module.w3.csm.oracle.perf_leeway_bp.return_value = 500
    module.state = state

    threshold = module._get_performance_threshold((0, 31), Mock())

    assert threshold == 0.95


def test_performance_threshold_handles_zero_leeway(module):
    state = State()
    state.data = {
        (0, 31): {
            ValidatorIndex(1): AttestationsAccumulator(10, 10),
            ValidatorIndex(2): AttestationsAccumulator(10, 10),
        },
    }
    module.w3.csm.oracle.perf_leeway_bp.return_value = 0
    module.state = state

    threshold = module._get_performance_threshold((0, 31), Mock())

    assert threshold == 1.0


def test_performance_threshold_handles_high_leeway(module):
    state = State()
    state.data = {
        (0, 31): {ValidatorIndex(1): AttestationsAccumulator(10, 1), ValidatorIndex(2): AttestationsAccumulator(10, 1)},
    }
    module.w3.csm.oracle.perf_leeway_bp.return_value = 5000
    module.state = state

    threshold = module._get_performance_threshold((0, 31), Mock())

    assert threshold == -0.4


def test_process_validator_duty_handles_above_threshold_performance():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    participation_shares = defaultdict(int)
    threshold = 0.5

    attestation_duty = AttestationsAccumulator(assigned=10, included=6)

    CSOracle.process_validator_duty(validator, attestation_duty, threshold, participation_shares, log_operator)

    assert participation_shares[validator.lido_id.operatorIndex] == 10
    assert log_operator.validators[validator.index].attestation_duty == attestation_duty


def test_process_validator_duty_handles_below_threshold_performance():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    participation_shares = defaultdict(int)
    threshold = 0.5

    attestation_duty = AttestationsAccumulator(assigned=10, included=4)

    CSOracle.process_validator_duty(validator, attestation_duty, threshold, participation_shares, log_operator)

    assert participation_shares[validator.lido_id.operatorIndex] == 0
    assert log_operator.validators[validator.index].attestation_duty == attestation_duty


def test_process_validator_duty_handles_non_empy_participation_shares():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    participation_shares = {validator.lido_id.operatorIndex: 25}
    threshold = 0.5

    attestation_duty = AttestationsAccumulator(assigned=10, included=6)

    CSOracle.process_validator_duty(validator, attestation_duty, threshold, participation_shares, log_operator)

    assert participation_shares[validator.lido_id.operatorIndex] == 35
    assert log_operator.validators[validator.index].attestation_duty == attestation_duty


def test_process_validator_duty_handles_no_duty_assigned():
    validator = LidoValidatorFactory.build()
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    participation_shares = defaultdict(int)
    threshold = 0.5

    CSOracle.process_validator_duty(validator, None, threshold, participation_shares, log_operator)

    assert participation_shares[validator.lido_id.operatorIndex] == 0
    assert validator.index not in log_operator.validators


def test_process_validator_duty_handles_slashed_validator():
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = True
    log_operator = Mock()
    log_operator.validators = defaultdict(ValidatorFrameSummary)
    participation_shares = defaultdict(int)
    threshold = 0.5

    attestation_duty = AttestationsAccumulator(assigned=1, included=1)

    CSOracle.process_validator_duty(validator, attestation_duty, threshold, participation_shares, log_operator)

    assert participation_shares[validator.lido_id.operatorIndex] == 0
    assert log_operator.validators[validator.index].slashed is True


def test_calc_rewards_distribution_in_frame_correctly_distributes_rewards():
    participation_shares = {NodeOperatorId(1): 100, NodeOperatorId(2): 200}
    rewards_to_distribute = Wei(1 * 10**18)

    rewards_distribution = CSOracle.calc_rewards_distribution_in_frame(participation_shares, rewards_to_distribute)

    assert rewards_distribution[NodeOperatorId(1)] == Wei(333333333333333333)
    assert rewards_distribution[NodeOperatorId(2)] == Wei(666666666666666666)


def test_calc_rewards_distribution_in_frame_handles_zero_participation():
    participation_shares = {NodeOperatorId(1): 0, NodeOperatorId(2): 0}
    rewards_to_distribute = Wei(1 * 10**18)

    rewards_distribution = CSOracle.calc_rewards_distribution_in_frame(participation_shares, rewards_to_distribute)

    assert rewards_distribution[NodeOperatorId(1)] == 0
    assert rewards_distribution[NodeOperatorId(2)] == 0


def test_calc_rewards_distribution_in_frame_handles_no_participation():
    participation_shares = {}
    rewards_to_distribute = Wei(1 * 10**18)

    rewards_distribution = CSOracle.calc_rewards_distribution_in_frame(participation_shares, rewards_to_distribute)

    assert len(rewards_distribution) == 0


def test_calc_rewards_distribution_in_frame_handles_partial_participation():
    participation_shares = {NodeOperatorId(1): 100, NodeOperatorId(2): 0}
    rewards_to_distribute = Wei(1 * 10**18)

    rewards_distribution = CSOracle.calc_rewards_distribution_in_frame(participation_shares, rewards_to_distribute)

    assert rewards_distribution[NodeOperatorId(1)] == Wei(1 * 10**18)
    assert rewards_distribution[NodeOperatorId(2)] == 0


def test_calc_rewards_distribution_in_frame_handles_negative_to_distribute():
    participation_shares = {NodeOperatorId(1): 100, NodeOperatorId(2): 200}
    rewards_to_distribute = Wei(-1)

    with pytest.raises(ValueError, match="Invalid rewards to distribute"):
        CSOracle.calc_rewards_distribution_in_frame(participation_shares, rewards_to_distribute)


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
    module.w3.csm.get_strikes_params = Mock(side_effect=lambda no_id, _: threshold_per_op[no_id])
    module._merge_strikes(acc, strikes_in_frame, frame_blockstamp=Mock())
    assert acc == expected
