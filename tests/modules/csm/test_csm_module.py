from dataclasses import dataclass
from typing import NoReturn
from unittest.mock import Mock, patch

import pytest

from src.constants import UINT64_MAX
from src.modules.csm.csm import CSOracle
from src.modules.csm.state import AttestationsAccumulator, State
from src.modules.submodules.types import CurrentFrame
from src.types import NodeOperatorId, SlotNumber, ValidatorIndex
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
    module.module = Mock()
    module.module_id = 1
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
            (None, NodeOperatorId(0)): [Mock(index=0)],
            (None, NodeOperatorId(1)): [Mock(index=1)],
            (None, NodeOperatorId(2)): [Mock(index=2)],  # stuck
            (None, NodeOperatorId(3)): [Mock(index=3)],
            (None, NodeOperatorId(4)): [Mock(index=4)],  # stuck
            (None, NodeOperatorId(5)): [Mock(index=5), Mock(index=6)],
            (None, NodeOperatorId(6)): [Mock(index=7), Mock(index=8)],
            (None, NodeOperatorId(7)): [Mock(index=9)],
            (None, NodeOperatorId(8)): [Mock(index=10), Mock(index=11, validator=Mock(slashed=True))],
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
    _, shares = module.calculate_distribution(blockstamp=Mock())

    assert tuple(shares.items()) == (
        (NodeOperatorId(0), 625),
        (NodeOperatorId(1), 3125),
        (NodeOperatorId(3), 3125),
        (NodeOperatorId(6), 3125),
        (NodeOperatorId(8), 3125),
    )


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
