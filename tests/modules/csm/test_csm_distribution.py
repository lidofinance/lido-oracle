from collections import defaultdict
from unittest.mock import Mock

import pytest
from web3.types import Wei

from src.constants import UINT64_MAX
from src.modules.csm.csm import CSOracle, CSMError
from src.modules.csm.log import ValidatorFrameSummary, OperatorFrameSummary
from src.modules.csm.state import AttestationsAccumulator, State
from src.types import NodeOperatorId, ValidatorIndex
from src.web3py.extensions import CSM
from tests.factory.no_registry import LidoValidatorFactory


@pytest.fixture(autouse=True)
def mock_get_module_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CSOracle, "_get_module_id", Mock())


@pytest.fixture()
def module(web3, csm: CSM):
    yield CSOracle(web3)


def test_calculate_distribution_handles_single_frame(module):
    module.state = Mock()
    module.state.frames = [(1, 2)]
    blockstamp = Mock()
    module.module_validators_by_node_operators = Mock()
    module._get_ref_blockstamp_for_frame = Mock(return_value=blockstamp)
    module.w3.csm.fee_distributor.shares_to_distribute = Mock(return_value=500)
    module._calculate_distribution_in_frame = Mock(return_value=({NodeOperatorId(1): 500}, Mock()))

    total_distributed, total_rewards, logs = module.calculate_distribution(blockstamp)

    assert total_distributed == 500
    assert total_rewards[NodeOperatorId(1)] == 500
    assert len(logs) == 1


def test_calculate_distribution_handles_multiple_frames(module):
    module.state = Mock()
    module.state.frames = [(1, 2), (3, 4), (5, 6)]
    blockstamp = Mock()
    module.module_validators_by_node_operators = Mock()
    module._get_ref_blockstamp_for_frame = Mock(return_value=blockstamp)
    module.w3.csm.fee_distributor.shares_to_distribute = Mock(return_value=800)
    module._calculate_distribution_in_frame = Mock(
        side_effect=[
            ({NodeOperatorId(1): 500}, Mock()),
            ({NodeOperatorId(1): 136}, Mock()),
            ({NodeOperatorId(1): 164}, Mock()),
        ]
    )

    total_distributed, total_rewards, logs = module.calculate_distribution(blockstamp)

    assert total_distributed == 800
    assert total_rewards[NodeOperatorId(1)] == 800
    assert len(logs) == 3


def test_calculate_distribution_handles_invalid_distribution(module):
    module.state = Mock()
    module.state.frames = [(1, 2)]
    blockstamp = Mock()
    module.module_validators_by_node_operators = Mock()
    module._get_ref_blockstamp_for_frame = Mock(return_value=blockstamp)
    module.w3.csm.fee_distributor.shares_to_distribute = Mock(return_value=500)
    module._calculate_distribution_in_frame = Mock(return_value=({NodeOperatorId(1): 600}, Mock()))

    with pytest.raises(CSMError, match="Invalid distribution"):
        module.calculate_distribution(blockstamp)


def test_calculate_distribution_in_frame_handles_stuck_operator(module):
    frame = Mock()
    blockstamp = Mock()
    rewards_to_distribute = UINT64_MAX
    operators_to_validators = {(Mock(), NodeOperatorId(1)): [LidoValidatorFactory.build()]}
    module.state = State()
    module.state.data = {frame: defaultdict(AttestationsAccumulator)}
    module.stuck_operators = Mock(return_value={NodeOperatorId(1)})
    module._get_performance_threshold = Mock()

    rewards_distribution, log = module._calculate_distribution_in_frame(
        frame, blockstamp, rewards_to_distribute, operators_to_validators
    )

    assert rewards_distribution[NodeOperatorId(1)] == 0
    assert log.operators[NodeOperatorId(1)].stuck is True
    assert log.operators[NodeOperatorId(1)].distributed == 0
    assert log.operators[NodeOperatorId(1)].validators == defaultdict(ValidatorFrameSummary)


def test_calculate_distribution_in_frame_handles_no_attestation_duty(module):
    frame = Mock()
    blockstamp = Mock()
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    module.state = State()
    module.state.data = {frame: defaultdict(AttestationsAccumulator)}
    module.stuck_operators = Mock(return_value=set())
    module._get_performance_threshold = Mock()

    rewards_distribution, log = module._calculate_distribution_in_frame(
        frame, blockstamp, rewards_to_distribute, operators_to_validators
    )

    assert rewards_distribution[node_operator_id] == 0
    assert log.operators[node_operator_id].stuck is False
    assert log.operators[node_operator_id].distributed == 0
    assert log.operators[node_operator_id].validators == defaultdict(ValidatorFrameSummary)


def test_calculate_distribution_in_frame_handles_above_threshold_performance(module):
    frame = Mock()
    blockstamp = Mock()
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    module.state = State()
    attestation_duty = AttestationsAccumulator(assigned=10, included=6)
    module.state.data = {frame: {validator.index: attestation_duty}}
    module.stuck_operators = Mock(return_value=set())
    module._get_performance_threshold = Mock(return_value=0.5)

    rewards_distribution, log = module._calculate_distribution_in_frame(
        frame, blockstamp, rewards_to_distribute, operators_to_validators
    )

    assert rewards_distribution[node_operator_id] > 0  # no need to check exact value
    assert log.operators[node_operator_id].stuck is False
    assert log.operators[node_operator_id].distributed > 0
    assert log.operators[node_operator_id].validators[validator.index].attestation_duty == attestation_duty


def test_calculate_distribution_in_frame_handles_below_threshold_performance(module):
    frame = Mock()
    blockstamp = Mock()
    rewards_to_distribute = UINT64_MAX
    validator = LidoValidatorFactory.build()
    validator.validator.slashed = False
    node_operator_id = validator.lido_id.operatorIndex
    operators_to_validators = {(Mock(), node_operator_id): [validator]}
    module.state = State()
    attestation_duty = AttestationsAccumulator(assigned=10, included=5)
    module.state.data = {frame: {validator.index: attestation_duty}}
    module.stuck_operators = Mock(return_value=set())
    module._get_performance_threshold = Mock(return_value=0.5)

    rewards_distribution, log = module._calculate_distribution_in_frame(
        frame, blockstamp, rewards_to_distribute, operators_to_validators
    )

    assert rewards_distribution[node_operator_id] == 0
    assert log.operators[node_operator_id].stuck is False
    assert log.operators[node_operator_id].distributed == 0
    assert log.operators[node_operator_id].validators[validator.index].attestation_duty == attestation_duty


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
