import logging
from dataclasses import dataclass
from typing import NoReturn
from unittest.mock import Mock, patch, PropertyMock

import pytest

from src.constants import UINT64_MAX
from src.modules.csm.csm import CSOracle
from src.modules.csm.state import AttestationsAccumulator, State
from src.modules.submodules.types import CurrentFrame
from src.types import EpochNumber, NodeOperatorId, SlotNumber, StakingModuleId, ValidatorIndex
from src.web3py.extensions.csm import CSM
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory


@pytest.fixture(autouse=True)
def mock_get_module_id(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CSOracle, "_get_module_id", Mock())


@pytest.fixture(autouse=True)
def mock_load_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(State, "load", Mock())


@pytest.fixture()
def module(web3, csm: CSM):
    yield CSOracle(web3)


def test_init(module: CSOracle):
    assert module


def test_stuck_operators(module: CSOracle, csm: CSM):
    module.module = Mock()  # type: ignore
    module.module_id = StakingModuleId(1)
    module.w3.cc = Mock()
    module.w3.lido_validators = Mock()
    module.w3.lido_contracts = Mock()
    module.w3.lido_validators.get_lido_node_operators_by_modules = Mock(
        return_value={
            1: {
                type('NodeOperator', (object,), {'id': 0, 'stuck_validators_count': 0})(),
                type('NodeOperator', (object,), {'id': 1, 'stuck_validators_count': 0})(),
                type('NodeOperator', (object,), {'id': 2, 'stuck_validators_count': 1})(),
                type('NodeOperator', (object,), {'id': 3, 'stuck_validators_count': 0})(),
                type('NodeOperator', (object,), {'id': 4, 'stuck_validators_count': 100500})(),
                type('NodeOperator', (object,), {'id': 5, 'stuck_validators_count': 100})(),
                type('NodeOperator', (object,), {'id': 6, 'stuck_validators_count': 0})(),
            },
            2: {},
            3: {},
            4: {},
        }
    )

    module.w3.csm.get_operators_with_stucks_in_range = Mock(
        return_value=[NodeOperatorId(2), NodeOperatorId(4), NodeOperatorId(6), NodeOperatorId(1337)]
    )

    module.current_frame_range = Mock(return_value=(69, 100))
    module.converter = Mock()
    module.converter.get_epoch_first_slot = Mock(return_value=lambda epoch: epoch * 32)

    l_blockstamp = Mock()
    blockstamp = Mock()
    l_blockstamp.block_hash = "0x01"
    blockstamp.slot_number = "1"
    blockstamp.block_hash = "0x02"

    with patch('src.modules.csm.csm.build_blockstamp', return_value=l_blockstamp):
        with patch('src.modules.csm.csm.get_next_non_missed_slot', return_value=Mock()):
            stuck = module.stuck_operators(blockstamp=blockstamp)

    assert stuck == {NodeOperatorId(2), NodeOperatorId(4), NodeOperatorId(5), NodeOperatorId(6), NodeOperatorId(1337)}


def test_calculate_distribution(module: CSOracle, csm: CSM):
    csm.fee_distributor.shares_to_distribute = Mock(return_value=10_000)
    csm.oracle.perf_leeway_bp = Mock(return_value=500)

    module.module_validators_by_node_operators = Mock(
        return_value={
            (None, NodeOperatorId(0)): [Mock(index=0, validator=Mock(slashed=False))],
            (None, NodeOperatorId(1)): [Mock(index=1, validator=Mock(slashed=False))],
            (None, NodeOperatorId(2)): [Mock(index=2, validator=Mock(slashed=False))],  # stuck
            (None, NodeOperatorId(3)): [Mock(index=3, validator=Mock(slashed=False))],
            (None, NodeOperatorId(4)): [Mock(index=4, validator=Mock(slashed=False))],  # stuck
            (None, NodeOperatorId(5)): [
                Mock(index=5, validator=Mock(slashed=False)),
                Mock(index=6, validator=Mock(slashed=False)),
            ],
            (None, NodeOperatorId(6)): [
                Mock(index=7, validator=Mock(slashed=False)),
                Mock(index=8, validator=Mock(slashed=False)),
            ],
            (None, NodeOperatorId(7)): [Mock(index=9, validator=Mock(slashed=False))],
            (None, NodeOperatorId(8)): [
                Mock(index=10, validator=Mock(slashed=False)),
                Mock(index=11, validator=Mock(slashed=True)),
            ],
            (None, NodeOperatorId(9)): [Mock(index=12, validator=Mock(slashed=True))],
        }
    )
    module.stuck_operators = Mock(
        return_value=[
            NodeOperatorId(2),
            NodeOperatorId(4),
        ]
    )

    module.state = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=200, assigned=200),  # short on frame
            ValidatorIndex(1): AttestationsAccumulator(included=1000, assigned=1000),
            ValidatorIndex(2): AttestationsAccumulator(included=1000, assigned=1000),
            ValidatorIndex(3): AttestationsAccumulator(included=999, assigned=1000),
            ValidatorIndex(4): AttestationsAccumulator(included=900, assigned=1000),
            ValidatorIndex(5): AttestationsAccumulator(included=500, assigned=1000),  # underperforming
            ValidatorIndex(6): AttestationsAccumulator(included=0, assigned=0),  # underperforming
            ValidatorIndex(7): AttestationsAccumulator(included=900, assigned=1000),
            ValidatorIndex(8): AttestationsAccumulator(included=500, assigned=1000),  # underperforming
            # ValidatorIndex(9): AttestationsAggregate(included=0, assigned=0),  # missing in state
            ValidatorIndex(10): AttestationsAccumulator(included=1000, assigned=1000),
            ValidatorIndex(11): AttestationsAccumulator(included=1000, assigned=1000),
            ValidatorIndex(12): AttestationsAccumulator(included=1000, assigned=1000),
        }
    )
    module.state.migrate(EpochNumber(100), EpochNumber(500))

    _, shares, log = module.calculate_distribution(blockstamp=Mock())

    assert tuple(shares.items()) == (
        (NodeOperatorId(0), 476),
        (NodeOperatorId(1), 2380),
        (NodeOperatorId(3), 2380),
        (NodeOperatorId(6), 2380),
        (NodeOperatorId(8), 2380),
    )

    assert tuple(log.operators.keys()) == (
        NodeOperatorId(0),
        NodeOperatorId(1),
        NodeOperatorId(2),
        NodeOperatorId(3),
        NodeOperatorId(4),
        NodeOperatorId(5),
        NodeOperatorId(6),
        # NodeOperatorId(7), # Missing in state
        NodeOperatorId(8),
        NodeOperatorId(9),
    )

    assert not log.operators[NodeOperatorId(1)].stuck

    assert log.operators[NodeOperatorId(2)].validators == {}
    assert log.operators[NodeOperatorId(2)].stuck
    assert log.operators[NodeOperatorId(4)].validators == {}
    assert log.operators[NodeOperatorId(4)].stuck

    assert 5 in log.operators[NodeOperatorId(5)].validators
    assert 6 in log.operators[NodeOperatorId(5)].validators
    assert 7 in log.operators[NodeOperatorId(6)].validators

    assert log.operators[NodeOperatorId(0)].distributed == 476
    assert log.operators[NodeOperatorId(1)].distributed == 2380
    assert log.operators[NodeOperatorId(2)].distributed == 0
    assert log.operators[NodeOperatorId(3)].distributed == 2380
    assert log.operators[NodeOperatorId(6)].distributed == 2380

    assert log.frame == (100, 500)
    assert log.threshold == module.state.get_network_aggr().perf - 0.05


# Static functions you were dreaming of for so long.


def last_slot_of_epoch(epoch: int) -> int:
    return epoch * 32 + 31


def slot_to_epoch(slot: int) -> int:
    return slot // 32


@pytest.fixture()
def mock_chain_config(module: CSOracle):
    module.get_chain_config = Mock(
        return_value=ChainConfigFactory.build(
            slots_per_epoch=32,
            seconds_per_slot=12,
            genesis_time=0,
        )
    )


# FAR_FUTURE_EPOCH from constants is not an epoch in a sense.
# The constant works as far the chain config isn't changed,
# especially genesis_time = 0.
FAR_FUTURE_EPOCH = (UINT64_MAX - 0) // 12 // 32


@dataclass(frozen=True)
class FrameTestParam:
    epochs_per_frame: int
    initial_ref_slot: int
    last_processing_ref_slot: int
    current_ref_slot: int
    finalized_slot: int
    expected_frame: tuple[int, int]


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(
            FrameTestParam(
                epochs_per_frame=0,
                initial_ref_slot=last_slot_of_epoch(FAR_FUTURE_EPOCH),
                last_processing_ref_slot=0,
                current_ref_slot=0,
                finalized_slot=0,
                expected_frame=(0, 0),
            ),
            id="initial_epoch_not_set",
            marks=pytest.mark.xfail(raises=ValueError),
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=1575,
                initial_ref_slot=2017759,
                last_processing_ref_slot=2168959,
                current_ref_slot=2219359,
                finalized_slot=2261631,
                expected_frame=(67780, 69354),
            ),
            id="holesky_testnet",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_ref_slot=last_slot_of_epoch(100),
                last_processing_ref_slot=0,
                current_ref_slot=0,
                finalized_slot=0,
                expected_frame=(69, 100),
            ),
            id="not_yet_reached_initial_epoch",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_ref_slot=last_slot_of_epoch(100),
                last_processing_ref_slot=0,
                current_ref_slot=last_slot_of_epoch(164),
                finalized_slot=last_slot_of_epoch(170),
                expected_frame=(69, 164),
            ),
            id="first_report_with_missed_frames",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_ref_slot=last_slot_of_epoch(100),
                last_processing_ref_slot=0,
                current_ref_slot=last_slot_of_epoch(100),
                finalized_slot=last_slot_of_epoch(120),
                expected_frame=(69, 100),
            ),
            id="frame_0",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=0,
                initial_ref_slot=last_slot_of_epoch(100),
                last_processing_ref_slot=last_slot_of_epoch(100),
                current_ref_slot=last_slot_of_epoch(132),
                finalized_slot=last_slot_of_epoch(124),
                expected_frame=(101, 132),
            ),
            id="frame_1",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=0,
                initial_ref_slot=last_slot_of_epoch(100),
                last_processing_ref_slot=last_slot_of_epoch(132),
                current_ref_slot=last_slot_of_epoch(196),
                finalized_slot=last_slot_of_epoch(200),
                expected_frame=(133, 196),
            ),
            id="one_frame_missed",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=0,
                initial_ref_slot=last_slot_of_epoch(100),
                last_processing_ref_slot=last_slot_of_epoch(90),
                current_ref_slot=last_slot_of_epoch(132),
                finalized_slot=last_slot_of_epoch(124),
                expected_frame=(91, 132),
            ),
            id="initial_epoch_moved_forward_with_missed_frame",
        ),
    ],
)
def test_current_frame_range(module: CSOracle, csm: CSM, mock_chain_config: NoReturn, param: FrameTestParam):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=slot_to_epoch(param.initial_ref_slot),
            epochs_per_frame=param.epochs_per_frame,
            fast_lane_length_slots=...,
        )
    )

    csm.get_csm_last_processing_ref_slot = Mock(return_value=param.last_processing_ref_slot)
    module.get_current_frame = Mock(
        return_value=CurrentFrame(
            ref_slot=SlotNumber(param.current_ref_slot),
            report_processing_deadline_slot=SlotNumber(0),
        )
    )
    module.get_initial_ref_slot = Mock(return_value=param.initial_ref_slot)
    bs = ReferenceBlockStampFactory.build(slot_number=param.finalized_slot)

    l_epoch, r_epoch = module.current_frame_range(bs)
    assert (l_epoch, r_epoch) == param.expected_frame


@pytest.fixture()
def mock_frame_config(module: CSOracle):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=0,
            epochs_per_frame=32,
            fast_lane_length_slots=...,
        )
    )


@dataclass(frozen=True)
class CollectDataTestParam:
    collect_blockstamp: Mock
    collect_frame_range: Mock
    report_blockstamp: Mock
    state: Mock
    expected_msg: str
    expected_result: bool | Exception


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(
            CollectDataTestParam(
                collect_blockstamp=Mock(slot_number=64),
                collect_frame_range=Mock(return_value=(0, 1)),
                report_blockstamp=Mock(ref_epoch=3),
                state=Mock(),
                expected_msg="Frame has been changed, but the change is not yet observed on finalized epoch 1",
                expected_result=False,
            ),
            id="frame_changed_forward",
        ),
        pytest.param(
            CollectDataTestParam(
                collect_blockstamp=Mock(slot_number=64),
                collect_frame_range=Mock(return_value=(0, 2)),
                report_blockstamp=Mock(ref_epoch=1),
                state=Mock(),
                expected_msg="Frame has been changed, but the change is not yet observed on finalized epoch 1",
                expected_result=False,
            ),
            id="frame_changed_backward",
        ),
        pytest.param(
            CollectDataTestParam(
                collect_blockstamp=Mock(slot_number=32),
                collect_frame_range=Mock(return_value=(1, 2)),
                report_blockstamp=Mock(ref_epoch=2),
                state=Mock(),
                expected_msg="The starting epoch of the frame is not finalized yet",
                expected_result=False,
            ),
            id="starting_epoch_not_finalized",
        ),
        pytest.param(
            CollectDataTestParam(
                collect_blockstamp=Mock(slot_number=32),
                collect_frame_range=Mock(return_value=(0, 2)),
                report_blockstamp=Mock(ref_epoch=2),
                state=Mock(
                    migrate=Mock(),
                    log_status=Mock(),
                    is_fulfilled=True,
                ),
                expected_msg="All epochs are already processed. Nothing to collect",
                expected_result=True,
            ),
            id="state_fulfilled",
        ),
        pytest.param(
            CollectDataTestParam(
                collect_blockstamp=Mock(slot_number=320),
                collect_frame_range=Mock(return_value=(0, 100)),
                report_blockstamp=Mock(ref_epoch=100),
                state=Mock(
                    migrate=Mock(),
                    log_status=Mock(),
                    unprocessed_epochs=[5],
                    is_fulfilled=False,
                ),
                expected_msg="Minimum checkpoint step is not reached, current delay is 2 epochs",
                expected_result=False,
            ),
            id="min_step_not_reached",
        ),
    ],
)
def test_collect_data(
    module: CSOracle,
    csm: CSM,
    param: CollectDataTestParam,
    mock_chain_config: NoReturn,
    mock_frame_config: NoReturn,
    caplog,
    monkeypatch,
):
    module.w3 = Mock()
    module._receive_last_finalized_slot = Mock()
    module.state = param.state
    module.current_frame_range = param.collect_frame_range
    module.get_blockstamp_for_report = Mock(return_value=param.report_blockstamp)

    with caplog.at_level(logging.DEBUG):
        if isinstance(param.expected_result, Exception):
            with pytest.raises(type(param.expected_result)):
                module.collect_data(blockstamp=param.collect_blockstamp)
        else:
            collected = module.collect_data(blockstamp=param.collect_blockstamp)
            assert collected == param.expected_result

    msg = list(filter(lambda log: param.expected_msg in log, caplog.messages))
    assert len(msg), f"Expected message '{param.expected_msg}' not found in logs"


def test_collect_data_outdated_checkpoint(
    module: CSOracle, csm: CSM, mock_chain_config: NoReturn, mock_frame_config: NoReturn, caplog
):
    module.w3 = Mock()
    module._receive_last_finalized_slot = Mock()
    module.state = Mock(
        migrate=Mock(),
        log_status=Mock(),
        unprocessed_epochs=list(range(0, 101)),
        is_fulfilled=False,
    )
    module.current_frame_range = Mock(side_effect=[(0, 100), (50, 150)])
    module.get_blockstamp_for_report = Mock(return_value=Mock(ref_epoch=100))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError):
            module.collect_data(blockstamp=Mock(slot_number=640))

    msg = list(
        filter(lambda log: "Checkpoints were prepared for an outdated frame, stop processing" in log, caplog.messages)
    )
    assert len(msg), "Expected message not found in logs"


def test_collect_data_fulfilled_state(
    module: CSOracle, csm: CSM, mock_chain_config: NoReturn, mock_frame_config: NoReturn, caplog
):
    module.w3 = Mock()
    module._receive_last_finalized_slot = Mock()
    module.state = Mock(
        migrate=Mock(),
        log_status=Mock(),
        unprocessed_epochs=list(range(0, 101)),
        is_fulfilled=PropertyMock(side_effect=[False, True]),
    )
    module.current_frame_range = Mock(return_value=(0, 100))
    module.get_blockstamp_for_report = Mock(return_value=Mock(ref_epoch=100))

    with caplog.at_level(logging.DEBUG):
        with patch('src.modules.csm.csm.FrameCheckpointProcessor.exec', return_value=None):
            collected = module.collect_data(blockstamp=Mock(slot_number=640))
            assert collected

    # assert that it is not early return from function
    msg = list(filter(lambda log: "All epochs are already processed. Nothing to collect" in log, caplog.messages))
    assert len(msg) == 0, "Unexpected message found in logs"
