import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, NoReturn, Type
from unittest.mock import Mock, PropertyMock, patch

import pytest
from hexbytes import HexBytes

from src.constants import UINT64_MAX
from src.modules.csm.csm import CSOracle, LastReport
from src.modules.csm.distribution import Distribution
from src.modules.csm.state import State
from src.modules.csm.tree import RewardsTree, StrikesTree
from src.modules.csm.types import StrikesList
from src.modules.submodules.oracle_module import ModuleExecuteDelay
from src.modules.submodules.types import ZERO_HASH, CurrentFrame
from src.providers.ipfs import CID
from src.types import NodeOperatorId, SlotNumber, FrameNumber
from src.utils.types import hex_str_to_bytes
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory


@pytest.fixture(autouse=True)
def mock_load_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(State, "load", Mock())


@pytest.fixture()
def module(web3):
    yield CSOracle(web3)


@pytest.mark.unit
def test_init(module: CSOracle):
    assert module


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
    expected_frame: tuple[int, int] | Type[ValueError]


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
                expected_frame=ValueError,
            ),
            id="initial_epoch_not_set",
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
@pytest.mark.unit
def test_current_frame_range(module: CSOracle, mock_chain_config: NoReturn, param: FrameTestParam):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=slot_to_epoch(param.initial_ref_slot),
            epochs_per_frame=param.epochs_per_frame,
            fast_lane_length_slots=...,
        )
    )

    module.w3.csm.get_csm_last_processing_ref_slot = Mock(return_value=param.last_processing_ref_slot)
    module.get_initial_or_current_frame = Mock(
        return_value=CurrentFrame(
            ref_slot=SlotNumber(param.current_ref_slot),
            report_processing_deadline_slot=SlotNumber(0),
        )
    )
    module.get_initial_ref_slot = Mock(return_value=param.initial_ref_slot)

    if param.expected_frame is ValueError:
        with pytest.raises(ValueError):
            module.get_epochs_range_to_process(ReferenceBlockStampFactory.build(slot_number=param.finalized_slot))
    else:
        bs = ReferenceBlockStampFactory.build(slot_number=param.finalized_slot)

        l_epoch, r_epoch = module.get_epochs_range_to_process(bs)
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
                expected_msg="Epochs range has been changed, but the change is not yet observed on finalized epoch 1",
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
                expected_msg="Epochs range has been changed, but the change is not yet observed on finalized epoch 1",
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
                expected_msg="The starting epoch of the epochs range is not finalized yet",
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
@pytest.mark.unit
def test_collect_data(
    module: CSOracle,
    param: CollectDataTestParam,
    mock_chain_config: NoReturn,
    mock_frame_config: NoReturn,
    caplog,
    monkeypatch,
):
    module.w3 = Mock()
    module._receive_last_finalized_slot = Mock()
    module.state = param.state
    module.get_epochs_range_to_process = param.collect_frame_range
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


@pytest.mark.unit
def test_collect_data_outdated_checkpoint(
    module: CSOracle, mock_chain_config: NoReturn, mock_frame_config: NoReturn, caplog
):
    module.w3 = Mock()
    module._receive_last_finalized_slot = Mock()
    module.state = Mock(
        migrate=Mock(),
        log_status=Mock(),
        unprocessed_epochs=list(range(0, 101)),
        is_fulfilled=False,
    )
    module.get_epochs_range_to_process = Mock(side_effect=[(0, 100), (50, 150)])
    module.get_blockstamp_for_report = Mock(return_value=Mock(ref_epoch=100))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError):
            module.collect_data(blockstamp=Mock(slot_number=640))

    msg = list(
        filter(
            lambda log: "Checkpoints were prepared for an outdated epochs range, stop processing" in log,
            caplog.messages,
        )
    )
    assert len(msg), "Expected message not found in logs"


@pytest.mark.unit
def test_collect_data_fulfilled_state(
    module: CSOracle, mock_chain_config: NoReturn, mock_frame_config: NoReturn, caplog
):
    module.w3 = Mock()
    module._reset_cycle_timeout = Mock()
    module._receive_last_finalized_slot = Mock()
    module.state = Mock(
        migrate=Mock(),
        log_status=Mock(),
        unprocessed_epochs=list(range(0, 101)),
    )
    type(module.state).is_fulfilled = PropertyMock(side_effect=[False, True])
    module.get_epochs_range_to_process = Mock(return_value=(0, 100))
    module.get_blockstamp_for_report = Mock(return_value=Mock(ref_epoch=100))

    with caplog.at_level(logging.DEBUG):
        with patch('src.modules.csm.csm.FrameCheckpointProcessor.exec', return_value=None):
            collected = module.collect_data(blockstamp=Mock(slot_number=640))
            assert collected is True

    # assert that it is not early return from function
    msg = list(filter(lambda log: "All epochs are already processed. Nothing to collect" in log, caplog.messages))
    assert len(msg) == 0, "Unexpected message found in logs"


@dataclass(frozen=True)
class BuildReportTestParam:
    last_report: LastReport
    curr_distribution: Mock
    curr_rewards_tree_root: HexBytes
    curr_rewards_tree_cid: CID | Literal[""]
    curr_strikes_tree_root: HexBytes
    curr_strikes_tree_cid: CID | Literal[""]
    curr_log_cid: CID
    expected_make_rewards_tree_call_args: tuple | None
    expected_func_result: tuple


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(
            BuildReportTestParam(
                last_report=Mock(
                    rewards_tree_root=HexBytes(ZERO_HASH),
                    rewards_tree_cid=None,
                    rewards=[],
                    strikes_tree_root=HexBytes(ZERO_HASH),
                    strikes_tree_cid=None,
                    strikes={},
                ),
                curr_distribution=Mock(
                    return_value=Mock(
                        spec=Distribution,
                        total_rewards=0,
                        total_rewards_map=defaultdict(int),
                        total_rebate=0,
                        strikes=defaultdict(dict),
                        logs=[Mock()],
                    )
                ),
                curr_rewards_tree_root=HexBytes(ZERO_HASH),
                curr_rewards_tree_cid="",
                curr_strikes_tree_root=HexBytes(ZERO_HASH),
                curr_strikes_tree_cid="",
                curr_log_cid=CID("QmLOG"),
                expected_make_rewards_tree_call_args=None,
                expected_func_result=(
                    1,
                    100500,
                    HexBytes(ZERO_HASH),
                    "",
                    CID("QmLOG"),
                    0,
                    0,
                    HexBytes(ZERO_HASH),
                    CID(""),
                ),
            ),
            id="empty_prev_report_and_no_new_distribution",
        ),
        pytest.param(
            BuildReportTestParam(
                last_report=Mock(
                    rewards_tree_root=HexBytes(ZERO_HASH),
                    rewards_tree_cid=None,
                    rewards=[],
                    strikes_tree_root=HexBytes(ZERO_HASH),
                    strikes_tree_cid=None,
                    strikes={},
                ),
                curr_distribution=Mock(
                    return_value=Mock(
                        spec=Distribution,
                        total_rewards=6,
                        total_rewards_map=defaultdict(
                            int, {NodeOperatorId(0): 1, NodeOperatorId(1): 2, NodeOperatorId(2): 3}
                        ),
                        total_rebate=1,
                        strikes=defaultdict(dict),
                        logs=[Mock()],
                    )
                ),
                curr_rewards_tree_root=HexBytes("NEW_TREE_ROOT".encode()),
                curr_rewards_tree_cid=CID("QmNEW_TREE"),
                curr_strikes_tree_root=HexBytes(ZERO_HASH),
                curr_strikes_tree_cid="",
                curr_log_cid=CID("QmLOG"),
                expected_make_rewards_tree_call_args=(
                    ({NodeOperatorId(0): 1, NodeOperatorId(1): 2, NodeOperatorId(2): 3},),
                ),
                expected_func_result=(
                    1,
                    100500,
                    HexBytes("NEW_TREE_ROOT".encode()),
                    CID("QmNEW_TREE"),
                    CID("QmLOG"),
                    6,
                    1,
                    HexBytes(ZERO_HASH),
                    CID(""),
                ),
            ),
            id="empty_prev_report_and_new_distribution",
        ),
        pytest.param(
            BuildReportTestParam(
                last_report=Mock(
                    rewards_tree_root=HexBytes("OLD_TREE_ROOT".encode()),
                    rewards_tree_cid=CID("QmOLD_TREE"),
                    rewards=[(NodeOperatorId(0), 100), (NodeOperatorId(1), 200), (NodeOperatorId(2), 300)],
                    strikes_tree_root=HexBytes(ZERO_HASH),
                    strikes_tree_cid=None,
                    strikes={},
                ),
                curr_distribution=Mock(
                    return_value=Mock(
                        spec=Distribution,
                        total_rewards=6,
                        total_rewards_map=defaultdict(
                            int,
                            {
                                NodeOperatorId(0): 101,
                                NodeOperatorId(1): 202,
                                NodeOperatorId(2): 300,
                                NodeOperatorId(3): 3,
                            },
                        ),
                        total_rebate=1,
                        strikes=defaultdict(dict),
                        logs=[Mock()],
                    )
                ),
                curr_rewards_tree_root=HexBytes("NEW_TREE_ROOT".encode()),
                curr_rewards_tree_cid=CID("QmNEW_TREE"),
                curr_strikes_tree_root=HexBytes(ZERO_HASH),
                curr_strikes_tree_cid="",
                curr_log_cid=CID("QmLOG"),
                expected_make_rewards_tree_call_args=(
                    ({NodeOperatorId(0): 101, NodeOperatorId(1): 202, NodeOperatorId(2): 300, NodeOperatorId(3): 3},),
                ),
                expected_func_result=(
                    1,
                    100500,
                    HexBytes("NEW_TREE_ROOT".encode()),
                    CID("QmNEW_TREE"),
                    CID("QmLOG"),
                    6,
                    1,
                    HexBytes(ZERO_HASH),
                    CID(""),
                ),
            ),
            id="non_empty_prev_report_and_new_distribution",
        ),
        pytest.param(
            BuildReportTestParam(
                last_report=Mock(
                    rewards_tree_root=HexBytes("OLD_TREE_ROOT".encode()),
                    rewards_tree_cid=CID("QmOLD_TREE"),
                    rewards=[(NodeOperatorId(0), 100), (NodeOperatorId(1), 200), (NodeOperatorId(2), 300)],
                    strikes_tree_root=HexBytes(ZERO_HASH),
                    strikes_tree_cid=None,
                    strikes={},
                ),
                curr_distribution=Mock(
                    return_value=Mock(
                        spec=Distribution,
                        total_rewards=0,
                        total_rewards_map=defaultdict(int),
                        total_rebate=0,
                        strikes=defaultdict(dict),
                        logs=[Mock()],
                    )
                ),
                curr_rewards_tree_root=HexBytes(32),
                curr_rewards_tree_cid="",
                curr_strikes_tree_root=HexBytes(ZERO_HASH),
                curr_strikes_tree_cid="",
                curr_log_cid=CID("QmLOG"),
                expected_make_rewards_tree_call_args=None,
                expected_func_result=(
                    1,
                    100500,
                    HexBytes("OLD_TREE_ROOT".encode()),
                    CID("QmOLD_TREE"),
                    CID("QmLOG"),
                    0,
                    0,
                    HexBytes(ZERO_HASH),
                    CID(""),
                ),
            ),
            id="non_empty_prev_report_and_no_new_distribution",
        ),
    ],
)
@pytest.mark.unit
def test_build_report(module: CSOracle, param: BuildReportTestParam):
    module.validate_state = Mock()
    module.report_contract.get_consensus_version = Mock(return_value=1)
    module._get_last_report = Mock(return_value=param.last_report)
    # mock current frame
    module.calculate_distribution = param.curr_distribution
    module.make_rewards_tree = Mock(return_value=Mock(root=param.curr_rewards_tree_root))
    module.make_strikes_tree = Mock(return_value=Mock(root=param.curr_strikes_tree_root))
    module.publish_tree = Mock(
        side_effect=[
            param.curr_rewards_tree_cid,
            param.curr_strikes_tree_cid,
        ]
    )
    module.publish_log = Mock(return_value=param.curr_log_cid)

    blockstamp = Mock(ref_slot=100500)
    report = module.build_report(blockstamp)

    assert module.make_rewards_tree.call_args == param.expected_make_rewards_tree_call_args
    assert report == param.expected_func_result


@pytest.mark.unit
def test_execute_module_not_collected(module: CSOracle):
    module._check_compatability = Mock(return_value=True)
    module.collect_data = Mock(return_value=False)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH


@pytest.mark.unit
def test_execute_module_skips_collecting_if_forward_compatible(module: CSOracle):
    module._check_compatability = Mock(return_value=False)
    module.collect_data = Mock(return_value=False)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    module.collect_data.assert_not_called()


@pytest.mark.unit
def test_execute_module_no_report_blockstamp(module: CSOracle):
    module._check_compatability = Mock(return_value=True)
    module.collect_data = Mock(return_value=True)
    module.get_blockstamp_for_report = Mock(return_value=None)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH


@pytest.mark.unit
def test_execute_module_processed(module: CSOracle):
    module.collect_data = Mock(return_value=True)
    module.get_blockstamp_for_report = Mock(return_value=Mock(slot_number=100500))
    module.process_report = Mock()
    module._check_compatability = Mock(return_value=True)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_SLOT


@dataclass(frozen=True)
class RewardsTreeTestParam:
    shares: dict[NodeOperatorId, int]
    expected_tree_values: list | Type[ValueError]


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(RewardsTreeTestParam(shares={}, expected_tree_values=ValueError), id="empty"),
    ],
)
def test_make_rewards_tree_negative(module: CSOracle, param: RewardsTreeTestParam):
    module.w3.csm.module.MAX_OPERATORS_COUNT = UINT64_MAX

    with pytest.raises(ValueError):
        module.make_rewards_tree(param.shares)


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(
            RewardsTreeTestParam(
                shares={NodeOperatorId(0): 1, NodeOperatorId(1): 2, NodeOperatorId(2): 3},
                expected_tree_values=[
                    (0, 1),
                    (1, 2),
                    (2, 3),
                ],
            ),
            id="normal_tree",
        ),
        pytest.param(
            RewardsTreeTestParam(
                shares={NodeOperatorId(0): 1},
                expected_tree_values=[
                    (0, 1),
                    (UINT64_MAX, 0),
                ],
            ),
            id="put_stone",
        ),
        pytest.param(
            RewardsTreeTestParam(
                shares={
                    NodeOperatorId(0): 1,
                    NodeOperatorId(1): 2,
                    NodeOperatorId(2): 3,
                    NodeOperatorId(UINT64_MAX): 0,
                },
                expected_tree_values=[
                    (0, 1),
                    (1, 2),
                    (2, 3),
                ],
            ),
            id="remove_stone",
        ),
    ],
)
@pytest.mark.unit
def test_make_rewards_tree(module: CSOracle, param: RewardsTreeTestParam):
    module.w3.csm.module.MAX_OPERATORS_COUNT = UINT64_MAX

    tree = module.make_rewards_tree(param.shares)
    assert tree.values == param.expected_tree_values


@dataclass(frozen=True)
class StrikesTreeTestParam:
    strikes: dict[tuple[NodeOperatorId, HexBytes], StrikesList]
    expected_tree_values: list | Type[ValueError]


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(StrikesTreeTestParam(strikes={}, expected_tree_values=ValueError), id="empty"),
    ],
)
@pytest.mark.unit
def test_make_strikes_tree_negative(module: CSOracle, param: StrikesTreeTestParam):
    module.w3.csm.module.MAX_OPERATORS_COUNT = UINT64_MAX

    with pytest.raises(ValueError):
        module.make_strikes_tree(param.strikes)


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(
            StrikesTreeTestParam(
                strikes={
                    (NodeOperatorId(0), HexBytes(b"07c0")): StrikesList([1]),
                    (NodeOperatorId(1), HexBytes(b"07e8")): StrikesList([1, 2]),
                    (NodeOperatorId(2), HexBytes(b"0682")): StrikesList([1, 2, 3]),
                },
                expected_tree_values=[
                    (NodeOperatorId(0), HexBytes(b"07c0"), StrikesList([1])),
                    (NodeOperatorId(1), HexBytes(b"07e8"), StrikesList([1, 2])),
                    (NodeOperatorId(2), HexBytes(b"0682"), StrikesList([1, 2, 3])),
                ],
            ),
            id="normal_tree",
        ),
        pytest.param(
            StrikesTreeTestParam(
                strikes={
                    (NodeOperatorId(0), HexBytes(b"07c0")): StrikesList([1]),
                },
                expected_tree_values=[
                    (NodeOperatorId(0), HexBytes(b"07c0"), StrikesList([1])),
                ],
            ),
            id="one_item_tree",
        ),
    ],
)
@pytest.mark.unit
def test_make_strikes_tree(module: CSOracle, param: StrikesTreeTestParam):
    module.w3.csm.module.MAX_OPERATORS_COUNT = UINT64_MAX

    tree = module.make_strikes_tree(param.strikes)
    assert tree.values == param.expected_tree_values


class TestLastReport:
    @pytest.mark.unit
    def test_load(self, web3: Web3):
        blockstamp = Mock()

        web3.csm.get_rewards_tree_root = Mock(return_value=HexBytes(b"42"))
        web3.csm.get_rewards_tree_cid = Mock(return_value=CID("QmRT"))
        web3.csm.get_strikes_tree_root = Mock(return_value=HexBytes(b"17"))
        web3.csm.get_strikes_tree_cid = Mock(return_value=CID("QmST"))

        last_report = LastReport.load(web3, blockstamp, FrameNumber(0))

        web3.csm.get_rewards_tree_root.assert_called_once_with(blockstamp)
        web3.csm.get_rewards_tree_cid.assert_called_once_with(blockstamp)
        web3.csm.get_strikes_tree_root.assert_called_once_with(blockstamp)
        web3.csm.get_strikes_tree_cid.assert_called_once_with(blockstamp)

        assert last_report.rewards_tree_root == HexBytes(b"42")
        assert last_report.rewards_tree_cid == CID("QmRT")
        assert last_report.strikes_tree_root == HexBytes(b"17")
        assert last_report.strikes_tree_cid == CID("QmST")

    @pytest.mark.unit
    def test_get_rewards_empty(self, web3: Web3):
        web3.ipfs = Mock(fetch=Mock())

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=HexBytes(ZERO_HASH),
            strikes_tree_root=Mock(),
            rewards_tree_cid=None,
            strikes_tree_cid=Mock(),
        )

        assert last_report.rewards == []
        web3.ipfs.fetch.assert_not_called()

    @pytest.mark.unit
    def test_get_rewards_okay(self, web3: Web3, rewards_tree: RewardsTree):
        encoded_tree = rewards_tree.encode()
        web3.ipfs = Mock(fetch=Mock(return_value=encoded_tree))

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=rewards_tree.root,
            strikes_tree_root=Mock(),
            rewards_tree_cid=CID("QmRT"),
            strikes_tree_cid=Mock(),
        )

        for value in rewards_tree.values:
            assert value in last_report.rewards

        web3.ipfs.fetch.assert_called_once_with(last_report.rewards_tree_cid, FrameNumber(0))

    @pytest.mark.unit
    def test_get_rewards_unexpected_root(self, web3: Web3, rewards_tree: RewardsTree):
        encoded_tree = rewards_tree.encode()
        web3.ipfs = Mock(fetch=Mock(return_value=encoded_tree))

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=HexBytes("DOES NOT MATCH".encode()),
            strikes_tree_root=Mock(),
            rewards_tree_cid=CID("QmRT"),
            strikes_tree_cid=Mock(),
        )

        with pytest.raises(ValueError, match="tree root"):
            last_report.rewards

        web3.ipfs.fetch.assert_called_once_with(last_report.rewards_tree_cid, FrameNumber(0))

    @pytest.mark.unit
    def test_get_strikes_empty(self, web3: Web3):
        web3.ipfs = Mock(fetch=Mock())

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=Mock(),
            strikes_tree_root=HexBytes(ZERO_HASH),
            rewards_tree_cid=Mock(),
            strikes_tree_cid=None,
        )

        assert last_report.strikes == {}
        web3.ipfs.fetch.assert_not_called()

    @pytest.mark.unit
    def test_get_strikes_okay(self, web3: Web3, strikes_tree: StrikesTree):
        encoded_tree = strikes_tree.encode()
        web3.ipfs = Mock(fetch=Mock(return_value=encoded_tree))

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=Mock(),
            strikes_tree_root=strikes_tree.root,
            rewards_tree_cid=Mock(),
            strikes_tree_cid=CID("QmST"),
        )

        for no_id, pubkey, value in strikes_tree.values:
            assert last_report.strikes[(no_id, pubkey)] == value

        web3.ipfs.fetch.assert_called_once_with(last_report.strikes_tree_cid, FrameNumber(0))

    @pytest.mark.unit
    def test_get_strikes_unexpected_root(self, web3: Web3, strikes_tree: StrikesTree):
        encoded_tree = strikes_tree.encode()
        web3.ipfs = Mock(fetch=Mock(return_value=encoded_tree))

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=Mock(),
            strikes_tree_root=HexBytes("DOES NOT MATCH".encode()),
            rewards_tree_cid=Mock(),
            strikes_tree_cid=CID("QmRT"),
        )

        with pytest.raises(ValueError, match="tree root"):
            last_report.strikes

        web3.ipfs.fetch.assert_called_once_with(last_report.strikes_tree_cid, FrameNumber(0))

    @pytest.fixture()
    def rewards_tree(self) -> RewardsTree:
        return RewardsTree.new(
            [
                (NodeOperatorId(0), 0),
                (NodeOperatorId(1), 1),
                (NodeOperatorId(2), 42),
                (NodeOperatorId(UINT64_MAX), 0),
            ]
        )

    @pytest.fixture()
    def strikes_tree(self) -> StrikesTree:
        return StrikesTree.new(
            [
                (NodeOperatorId(0), HexBytes(hex_str_to_bytes("0x00")), StrikesList([0])),
                (NodeOperatorId(1), HexBytes(hex_str_to_bytes("0x01")), StrikesList([1])),
                (NodeOperatorId(1), HexBytes(hex_str_to_bytes("0x02")), StrikesList([1])),
                (NodeOperatorId(2), HexBytes(hex_str_to_bytes("0x03")), StrikesList([1])),
                (NodeOperatorId(UINT64_MAX), HexBytes(hex_str_to_bytes("0x64")), StrikesList([1, 0, 1])),
            ]
        )
