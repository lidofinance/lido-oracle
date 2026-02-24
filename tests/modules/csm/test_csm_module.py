import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, NoReturn
from unittest.mock import Mock, PropertyMock, call, patch

import pytest
from hexbytes import HexBytes

from src.constants import STAKING_MODULE_LOGS_VERSION, UINT64_MAX
from src.modules.common.types import ZERO_HASH, CurrentFrame, ModuleExecuteDelay
from src.modules.oracles.staking_modules.base import SMPerformanceOracleError
from src.modules.oracles.staking_modules.common.distribution import Distribution
from src.modules.oracles.staking_modules.common.helpers.last_report import LastReport
from src.modules.oracles.staking_modules.common.log import Logs
from src.modules.oracles.staking_modules.common.state import State
from src.modules.oracles.staking_modules.common.tree import RewardsTree, StrikesTree
from src.modules.oracles.staking_modules.common.types import StrikesList
from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from src.modules.sidecars.performance.common.db import Duty
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.execution.exceptions import InconsistentData
from src.providers.ipfs import CID
from src.types import EpochNumber, FrameNumber, Gwei, NodeOperatorId, SlotNumber, ValidatorIndex
from src.utils.types import hex_str_to_bytes
from src.web3py.types import Web3StakingModule
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory


@pytest.fixture(autouse=True)
def mock_load_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(State, "load", Mock())


@pytest.fixture()
def module(web3):
    yield CSPerformanceOracle(web3)


@pytest.mark.unit
def test_init(module: CSPerformanceOracle):
    assert module


@pytest.mark.unit
def test_shutdown_calls_cleanup(module: CSPerformanceOracle):
    module.w3 = Mock()
    module.w3.performance.get_epochs_demand = Mock(return_value=Mock())
    module.w3.performance.delete_epochs_demand = Mock()
    module.shutdown()
    module.w3.performance.get_epochs_demand.assert_called_once_with("CSPerformanceOracle")
    module.w3.performance.delete_epochs_demand.assert_called_once_with("CSPerformanceOracle")


# Static functions you were dreaming of for so long.


def last_slot_of_epoch(epoch: int) -> int:
    return epoch * 32 + 31


def slot_to_epoch(slot: int) -> int:
    return slot // 32


def make_validator(index: int, activation_epoch: int = 0, exit_epoch: int = 100) -> Validator:
    return Validator(
        index=ValidatorIndex(index),
        balance=Gwei(0),
        validator=ValidatorState(
            pubkey=f"0x{index:02x}",
            withdrawal_credentials="0x00",
            effective_balance=Gwei(0),
            slashed=False,
            activation_eligibility_epoch=EpochNumber(activation_epoch),
            activation_epoch=EpochNumber(activation_epoch),
            exit_epoch=EpochNumber(exit_epoch),
            withdrawable_epoch=EpochNumber(exit_epoch + 1),
        ),
    )


@pytest.fixture()
def mock_chain_config(module: CSPerformanceOracle):
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
    expected_frame: tuple[int, int] | type[Exception]


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
        # NOTE: Impossible case in current processing
        # pytest.param(
        #     FrameTestParam(
        #         epochs_per_frame=32,
        #         initial_ref_slot=last_slot_of_epoch(100),
        #         last_processing_ref_slot=0,
        #         current_ref_slot=0,
        #         finalized_slot=0,
        #         expected_frame=(69, 100),
        #     ),
        #     id="not_yet_reached_initial_epoch",
        # ),
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
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_ref_slot=last_slot_of_epoch(10),
                last_processing_ref_slot=last_slot_of_epoch(20),
                current_ref_slot=last_slot_of_epoch(15),
                finalized_slot=last_slot_of_epoch(15),
                expected_frame=InconsistentData,
            ),
            id="last_processing_ref_slot_in_future",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=4,
                initial_ref_slot=last_slot_of_epoch(1),
                last_processing_ref_slot=0,
                current_ref_slot=last_slot_of_epoch(1),
                finalized_slot=last_slot_of_epoch(1),
                expected_frame=SMPerformanceOracleError,
            ),
            id="negative_first_frame",
        ),
    ],
)
@pytest.mark.unit
def test_current_frame_range(module: CSPerformanceOracle, mock_chain_config: NoReturn, param: FrameTestParam):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=slot_to_epoch(param.initial_ref_slot),
            epochs_per_frame=param.epochs_per_frame,
            fast_lane_length_slots=...,
        )
    )

    module.w3.staking_module.get_last_processing_ref_slot = Mock(return_value=param.last_processing_ref_slot)
    module.get_initial_or_current_frame = Mock(
        return_value=CurrentFrame(
            ref_slot=SlotNumber(param.current_ref_slot),
            report_processing_deadline_slot=SlotNumber(0),
        )
    )
    module.get_initial_ref_slot = Mock(return_value=param.initial_ref_slot)

    ref_epoch = slot_to_epoch(param.current_ref_slot)
    if isinstance(param.expected_frame, type) and issubclass(param.expected_frame, Exception):
        with pytest.raises(param.expected_frame):
            module._get_epochs_range_to_process(
                ReferenceBlockStampFactory.build(slot_number=param.current_ref_slot, ref_epoch=ref_epoch)
            )
    else:
        bs = ReferenceBlockStampFactory.build(slot_number=param.current_ref_slot, ref_epoch=ref_epoch)

        l_epoch, r_epoch = module._get_epochs_range_to_process(bs)
        assert (l_epoch, r_epoch) == param.expected_frame


@pytest.mark.unit
def test__set_epochs_range_to_collect_posts_new_demand(module: CSPerformanceOracle, mock_chain_config: NoReturn):
    blockstamp = ReferenceBlockStampFactory.build()
    module.state = Mock(migrate=Mock(), log_progress=Mock())
    converter = Mock()
    converter.frame_config = Mock(epochs_per_frame=4)
    module._converter = Mock(return_value=converter)
    module._get_epochs_range_to_process = Mock(return_value=(10, 20))
    module.w3 = Mock()
    module.w3.performance.is_range_available = Mock(return_value=False)
    module.w3.performance.get_epochs_demand = Mock(return_value={})
    module.w3.performance.post_epochs_demand = Mock()

    module._set_epochs_range_to_collect(blockstamp)

    module.state.migrate.assert_called_once_with(10, 20, 4)
    module.state.log_progress.assert_called_once()
    module.w3.performance.is_range_available.assert_called_once_with(10, 20)
    module.w3.performance.get_epochs_demand.assert_called_once()
    module.w3.performance.post_epochs_demand.assert_called_once_with("CSPerformanceOracle", 10, 20)


@pytest.mark.unit
def test__set_epochs_range_to_collect_skips_post_when_demand_same(
    module: CSPerformanceOracle, mock_chain_config: NoReturn
):
    blockstamp = ReferenceBlockStampFactory.build()
    module.state = Mock(migrate=Mock(), log_progress=Mock())
    converter = Mock()
    converter.frame_config = Mock(epochs_per_frame=4)
    module._converter = Mock(return_value=converter)
    module._get_epochs_range_to_process = Mock(return_value=(10, 20))
    module.w3 = Mock()
    module.w3.performance.get_epochs_demands = Mock(return_value={"CSPerformanceOracle": (10, 20)})
    module.w3.performance.post_epochs_demand = Mock()

    module._set_epochs_range_to_collect(blockstamp)

    module.state.migrate.assert_called_once_with(10, 20, 4)
    module.state.log_progress.assert_called_once()
    module.w3.performance.post_epochs_demand.assert_not_called()


@pytest.fixture()
def mock_frame_config(module: CSPerformanceOracle):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=0,
            epochs_per_frame=32,
            fast_lane_length_slots=...,
        )
    )


@dataclass(frozen=True)
class CollectDataCase:
    frames: list[tuple[int, int]]
    range_available: bool
    is_fulfilled_side_effect: list[bool]
    expected_result: bool
    expect_fulfill_call: bool
    expect_range_call: tuple[int, int]
    check_no_completed_msg: bool


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            CollectDataCase(
                frames=[(10, 12)],
                range_available=False,
                is_fulfilled_side_effect=[False],
                expected_result=False,
                expect_fulfill_call=False,
                expect_range_call=(10, 12),
                check_no_completed_msg=False,
            ),
            id="range_not_available",
        ),
        pytest.param(
            CollectDataCase(
                frames=[(10, 12)],
                range_available=True,
                is_fulfilled_side_effect=[False, True],
                expected_result=True,
                expect_fulfill_call=True,
                expect_range_call=(10, 12),
                check_no_completed_msg=False,
            ),
            id="range_available",
        ),
        pytest.param(
            CollectDataCase(
                frames=[(0, 100)],
                range_available=True,
                is_fulfilled_side_effect=[False, True],
                expected_result=True,
                expect_fulfill_call=True,
                expect_range_call=(0, 100),
                check_no_completed_msg=True,
            ),
            id="fulfilled_state",
        ),
    ],
)
@pytest.mark.unit
def test__collect_data_handles_range_availability(
    module: CSPerformanceOracle, mock_chain_config: NoReturn, mock_frame_config: NoReturn, caplog, case: CollectDataCase
):
    module.w3 = Mock()
    module.w3.performance.is_range_available = Mock(return_value=case.range_available)
    module._fulfill_state = Mock()
    state = Mock(frames=case.frames)
    type(state).is_fulfilled = PropertyMock(side_effect=case.is_fulfilled_side_effect)
    module.state = state

    with caplog.at_level(logging.DEBUG):
        result = module._collect_data()

    assert result is case.expected_result
    module.w3.performance.is_range_available.assert_called_once_with(*case.expect_range_call)
    if case.expect_fulfill_call:
        module._fulfill_state.assert_called_once()
    else:
        module._fulfill_state.assert_not_called()

    if case.check_no_completed_msg:
        assert "All epochs are already processed. Nothing to collect" not in caplog.messages


@pytest.mark.unit
def test_fulfill_state_handles_epoch_data(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator_a = make_validator(0, activation_epoch=0, exit_epoch=10)
    validator_b = make_validator(1, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators = Mock(return_value=[validator_a, validator_b])

    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                attestations=[validator_a.index],
                proposals_vids=[int(validator_a.index), int(validator_b.index)],
                proposals_flags=[True, False],
                syncs_vids=[int(validator_a.index), int(validator_b.index)],
                syncs_misses=[0, 1],
            ),
            Duty(
                epoch=1,
                attestations=[],
                proposals_vids=[int(validator_b.index)],
                proposals_flags=[True],
                syncs_vids=[int(validator_a.index), int(validator_b.index)],
                syncs_misses=[2, 3],
            ),
        ]
    )
    frames = [(0, 1)]
    unprocessed = {0, 1}

    state = Mock()
    state.frames = frames
    state.unprocessed_epochs = unprocessed
    state.save_att_duty = Mock()
    state.save_prop_duty = Mock()
    state.save_sync_duty = Mock()
    state.add_processed_epoch = Mock()
    state.log_progress = Mock()
    module.state = state

    module._fulfill_state()

    module._receive_last_finalized_slot.assert_called_once()
    module.w3.cc.get_validators.assert_called_once_with("finalized")

    module.w3.performance.get_epochs_data.assert_called_once_with(0, 1)
    assert state.save_att_duty.call_args_list == [
        call(EpochNumber(0), validator_a.index, included=False),
        call(EpochNumber(0), validator_b.index, included=True),
        call(EpochNumber(1), validator_a.index, included=True),
        call(EpochNumber(1), validator_b.index, included=True),
    ]
    assert state.save_prop_duty.call_args_list == [
        call(EpochNumber(0), ValidatorIndex(int(validator_a.index)), included=True),
        call(EpochNumber(0), ValidatorIndex(int(validator_b.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(validator_b.index)), included=True),
    ]
    assert state.save_sync_duty.call_args_list == [
        call(EpochNumber(0), ValidatorIndex(int(validator_a.index)), included=True),
        call(EpochNumber(0), ValidatorIndex(int(validator_b.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(validator_a.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(validator_a.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(validator_b.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(validator_b.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(validator_b.index)), included=False),
    ]
    assert state.add_processed_epoch.call_args_list == [
        call(EpochNumber(0)),
        call(EpochNumber(1)),
    ]
    assert state.log_progress.call_count == 1


@pytest.mark.unit
def test_fulfill_state_raises_on_inactive_missed_attestation(module: CSPerformanceOracle):
    inactive_validator = make_validator(5, activation_epoch=10, exit_epoch=20)
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    module.w3 = Mock()
    module.w3.cc.get_validators = Mock(return_value=[inactive_validator])
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                attestations=[inactive_validator.index],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
    )
    state = Mock()
    state.frames = [(0, 0)]
    state.unprocessed_epochs = {0}
    state.save_att_duty = Mock()
    state.save_prop_duty = Mock()
    state.save_sync_duty = Mock()
    state.add_processed_epoch = Mock()
    state.log_progress = Mock()
    module.state = state

    with pytest.raises(ValueError, match="not active"):
        module._fulfill_state()

    module.w3.performance.get_epochs_data.assert_called_once_with(0, 0)
    state.save_att_duty.assert_not_called()
    state.add_processed_epoch.assert_not_called()


@pytest.mark.unit
def test_fulfill_state_skips_inactive_validators_across_epochs(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    active_all = make_validator(0, activation_epoch=0, exit_epoch=10)
    active_late = make_validator(1, activation_epoch=1, exit_epoch=10)
    exit_early = make_validator(2, activation_epoch=0, exit_epoch=1)
    inactive_all = make_validator(3, activation_epoch=10, exit_epoch=20)
    module.w3 = Mock()
    module.w3.cc.get_validators = Mock(return_value=[active_all, active_late, exit_early, inactive_all])
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                attestations=[exit_early.index],
                proposals_vids=[int(active_all.index)],
                proposals_flags=[True],
                syncs_vids=[int(active_all.index)],
                syncs_misses=[0],
            ),
            Duty(
                epoch=1,
                attestations=[active_all.index],
                proposals_vids=[int(active_late.index), int(active_all.index)],
                proposals_flags=[True, False],
                syncs_vids=[int(active_all.index), int(active_late.index)],
                syncs_misses=[1, 0],
            ),
            Duty(
                epoch=2,
                attestations=[],
                proposals_vids=[int(active_all.index)],
                proposals_flags=[True],
                syncs_vids=[int(active_all.index)],
                syncs_misses=[1],
            ),
        ]
    )
    state = Mock()
    state.frames = [(0, 2)]
    state.unprocessed_epochs = {0, 1, 2}
    state.save_att_duty = Mock()
    state.save_prop_duty = Mock()
    state.save_sync_duty = Mock()
    state.add_processed_epoch = Mock()
    state.log_progress = Mock()
    module.state = state

    module._fulfill_state()

    module.w3.performance.get_epochs_data.assert_called_once_with(0, 2)
    assert state.save_att_duty.call_args_list == [
        call(EpochNumber(0), active_all.index, included=True),
        call(EpochNumber(0), exit_early.index, included=False),
        call(EpochNumber(1), active_all.index, included=False),
        call(EpochNumber(1), active_late.index, included=True),
        call(EpochNumber(2), active_all.index, included=True),
        call(EpochNumber(2), active_late.index, included=True),
    ]
    assert state.save_prop_duty.call_args_list == [
        call(EpochNumber(0), ValidatorIndex(int(active_all.index)), included=True),
        call(EpochNumber(1), ValidatorIndex(int(active_late.index)), included=True),
        call(EpochNumber(1), ValidatorIndex(int(active_all.index)), included=False),
        call(EpochNumber(2), ValidatorIndex(int(active_all.index)), included=True),
    ]
    assert state.save_sync_duty.call_args_list == [
        call(EpochNumber(0), ValidatorIndex(int(active_all.index)), included=True),
        call(EpochNumber(1), ValidatorIndex(int(active_all.index)), included=False),
        call(EpochNumber(1), ValidatorIndex(int(active_late.index)), included=True),
        call(EpochNumber(2), ValidatorIndex(int(active_all.index)), included=False),
    ]
    state.add_processed_epoch.assert_has_calls([call(EpochNumber(0)), call(EpochNumber(1)), call(EpochNumber(2))])


@pytest.mark.unit
def test_validate_state_uses_ref_epoch(module: CSPerformanceOracle):
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=123)
    module._get_epochs_range_to_process = Mock(return_value=(5, 10))
    module.state = Mock(validate=Mock())

    module._validate_state(blockstamp)

    module._get_epochs_range_to_process.assert_called_once_with(blockstamp)
    module.state.validate.assert_called_once_with(5, 123)


@pytest.mark.parametrize(
    "last_ref_slot,current_ref_slot,expected",
    [
        pytest.param(64, 64, True, id="already_submitted"),
        pytest.param(32, 64, False, id="pending_submission"),
    ],
)
@pytest.mark.unit
def test_is_main_data_submitted(module: CSPerformanceOracle, last_ref_slot: int, current_ref_slot: int, expected: bool):
    blockstamp = ReferenceBlockStampFactory.build()
    module.w3 = Mock()
    module.w3.staking_module.get_last_processing_ref_slot = Mock(return_value=SlotNumber(last_ref_slot))
    module.get_initial_or_current_frame = Mock(
        return_value=CurrentFrame(
            ref_slot=SlotNumber(current_ref_slot),
            report_processing_deadline_slot=SlotNumber(0),
        )
    )

    assert module.is_main_data_submitted(blockstamp) is expected


@pytest.mark.parametrize("submitted", [True, False])
@pytest.mark.unit
def test_is_contract_reportable_relies_on_is_main_data_submitted(module: CSPerformanceOracle, submitted: bool):
    module.is_main_data_submitted = Mock(return_value=submitted)

    result = module.is_contract_reportable(ReferenceBlockStampFactory.build())

    module.is_main_data_submitted.assert_called_once()
    assert result is (not submitted)


@pytest.mark.unit
def test_publish_tree_uploads_encoded_tree(module: CSPerformanceOracle):
    tree = Mock()
    tree.encode.return_value = b"tree"
    module.w3 = Mock()
    module.w3.ipfs.publish = Mock(return_value=CID("QmTree"))

    cid = module._publish_tree(tree)

    module.w3.ipfs.publish.assert_called_once_with(b"tree")
    assert cid == CID("QmTree")


@pytest.mark.unit
def test_publish_log_uploads_encoded_log(module: CSPerformanceOracle, monkeypatch: pytest.MonkeyPatch):
    logs = Logs()
    logs.frames = [Mock()]
    encode_mock = Mock(return_value=b"log")
    logs.encode = encode_mock
    module.w3 = Mock()
    module.w3.ipfs.publish = Mock(return_value=CID("QmLog"))

    cid = module._publish_log(logs)

    encode_mock.assert_called_once()
    module.w3.ipfs.publish.assert_called_once_with(b"log")
    assert cid == CID("QmLog")


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
                        logs=Logs(frames=[Mock()]),
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
                        logs=Logs(frames=[Mock()]),
                    )
                ),
                curr_rewards_tree_root=HexBytes(b"NEW_TREE_ROOT"),
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
                    HexBytes(b"NEW_TREE_ROOT"),
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
                    rewards_tree_root=HexBytes(b"OLD_TREE_ROOT"),
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
                        logs=Logs(frames=[Mock()]),
                    )
                ),
                curr_rewards_tree_root=HexBytes(b"NEW_TREE_ROOT"),
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
                    HexBytes(b"NEW_TREE_ROOT"),
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
                    rewards_tree_root=HexBytes(b"OLD_TREE_ROOT"),
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
                        logs=Logs(frames=[Mock()]),
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
                    HexBytes(b"OLD_TREE_ROOT"),
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
def test_build_report(module: CSPerformanceOracle, param: BuildReportTestParam):
    module._validate_state = Mock()
    module.report_contract.get_consensus_version = Mock(return_value=1)
    module._calculate_distribution = Mock(return_value=(param.curr_distribution(), param.last_report))
    module._make_rewards_tree = Mock(return_value=Mock(root=param.curr_rewards_tree_root))
    module._make_strikes_tree = Mock(return_value=Mock(root=param.curr_strikes_tree_root))
    module._publish_tree = Mock(
        side_effect=[
            param.curr_rewards_tree_cid,
            param.curr_strikes_tree_cid,
        ]
    )
    module._publish_log = Mock(return_value=param.curr_log_cid)

    blockstamp = Mock(ref_slot=100500)
    report = module.build_report(blockstamp)

    assert module._make_rewards_tree.call_args == param.expected_make_rewards_tree_call_args
    assert report == param.expected_func_result
    assert module._publish_log.call_args[0][0]._ver == STAKING_MODULE_LOGS_VERSION


@pytest.mark.unit
def test_execute_module_not_collected(module: CSPerformanceOracle):
    module._check_compatibility = Mock(return_value=True)
    module.get_blockstamp_for_report = Mock(return_value=Mock(slot_number=100500))
    module._set_epochs_range_to_collect = Mock()
    module._collect_data = Mock(return_value=False)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH


@pytest.mark.unit
def test_execute_module_skips_collecting_if_forward_compatible(module: CSPerformanceOracle):
    module._check_compatibility = Mock(return_value=False)
    module._collect_data = Mock(return_value=False)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    module._collect_data.assert_not_called()


@pytest.mark.unit
def test_execute_module_no_report_blockstamp(module: CSPerformanceOracle):
    module._check_compatibility = Mock(return_value=True)
    module._set_epochs_range_to_collect = Mock()
    module._collect_data = Mock(return_value=True)
    module.get_blockstamp_for_report = Mock(return_value=None)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH


@pytest.mark.unit
def test_execute_module_processed(module: CSPerformanceOracle):
    module._set_epochs_range_to_collect = Mock()
    module._collect_data = Mock(return_value=True)
    module.get_blockstamp_for_report = Mock(return_value=Mock(slot_number=100500))
    module.process_report = Mock()
    module._check_compatibility = Mock(return_value=True)

    execute_delay = module.execute_module(
        last_finalized_blockstamp=Mock(slot_number=100500),
    )
    assert execute_delay is ModuleExecuteDelay.NEXT_SLOT


@pytest.mark.unit
def test_calculate_distribution_lru_cache(module: CSPerformanceOracle):
    blockstamp = Mock()
    last_report = Mock()
    last_report.strikes = {}  # Create proper dictionary instead of Mock
    last_report.rewards = []  # Add empty list instead of Mock for rewards
    mock_distribution_result = Mock()

    with patch('src.modules.oracles.staking_modules.base.Distribution') as MockDistribution:
        mock_distribution_instance = MockDistribution.return_value
        mock_distribution_instance.calculate.return_value = mock_distribution_result

        module._converter = Mock()
        module.state = Mock()
        module._get_last_report = Mock(return_value=last_report)

        result1, last_report1 = module._calculate_distribution(blockstamp)

        result2, last_report2 = module._calculate_distribution(blockstamp)

        assert result1 is result2
        assert last_report1 is last_report2
        assert result1 is mock_distribution_result
        assert last_report1 is last_report

        assert MockDistribution.call_count == 1
        assert mock_distribution_instance.calculate.call_count == 1

        module._calculate_distribution.cache_clear()

        result3, last_report3 = module._calculate_distribution(blockstamp)

        assert MockDistribution.call_count == 2
        assert result3 is mock_distribution_result


@dataclass(frozen=True)
class RewardsTreeTestParam:
    shares: dict[NodeOperatorId, int]
    expected_tree_values: list | type[ValueError]


@pytest.mark.unit
@pytest.mark.parametrize(
    "param",
    [
        pytest.param(RewardsTreeTestParam(shares={}, expected_tree_values=ValueError), id="empty"),
    ],
)
def test_make_rewards_tree_negative(module: CSPerformanceOracle, param: RewardsTreeTestParam):
    module.w3.staking_module.module.MAX_OPERATORS_COUNT = UINT64_MAX

    with pytest.raises(ValueError):
        module._make_rewards_tree(param.shares)


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
def test_make_rewards_tree(module: CSPerformanceOracle, param: RewardsTreeTestParam):
    module.w3.staking_module.module.MAX_OPERATORS_COUNT = UINT64_MAX

    tree = module._make_rewards_tree(param.shares)
    assert tree.values == param.expected_tree_values


@dataclass(frozen=True)
class StrikesTreeTestParam:
    strikes: dict[tuple[NodeOperatorId, HexBytes], StrikesList]
    expected_tree_values: list | type[ValueError]


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(StrikesTreeTestParam(strikes={}, expected_tree_values=ValueError), id="empty"),
    ],
)
@pytest.mark.unit
def test_make_strikes_tree_negative(module: CSPerformanceOracle, param: StrikesTreeTestParam):
    module.w3.staking_module.module.MAX_OPERATORS_COUNT = UINT64_MAX

    with pytest.raises(ValueError):
        module._make_strikes_tree(param.strikes)


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
def test_make_strikes_tree(module: CSPerformanceOracle, param: StrikesTreeTestParam):
    module.w3.staking_module.module.MAX_OPERATORS_COUNT = UINT64_MAX

    tree = module._make_strikes_tree(param.strikes)
    assert tree.values == param.expected_tree_values


class TestLastReport:
    @pytest.mark.unit
    def test_load(self, web3: Web3StakingModule):
        blockstamp = Mock()

        web3.staking_module.get_rewards_tree_root = Mock(return_value=HexBytes(b"42"))
        web3.staking_module.get_rewards_tree_cid = Mock(return_value=CID("QmRT"))
        web3.staking_module.get_strikes_tree_root = Mock(return_value=HexBytes(b"17"))
        web3.staking_module.get_strikes_tree_cid = Mock(return_value=CID("QmST"))

        last_report = LastReport.load(web3, blockstamp, FrameNumber(0))

        web3.staking_module.get_rewards_tree_root.assert_called_once_with(blockstamp)
        web3.staking_module.get_rewards_tree_cid.assert_called_once_with(blockstamp)
        web3.staking_module.get_strikes_tree_root.assert_called_once_with(blockstamp)
        web3.staking_module.get_strikes_tree_cid.assert_called_once_with(blockstamp)

        assert last_report.rewards_tree_root == HexBytes(b"42")
        assert last_report.rewards_tree_cid == CID("QmRT")
        assert last_report.strikes_tree_root == HexBytes(b"17")
        assert last_report.strikes_tree_cid == CID("QmST")

    @pytest.mark.unit
    def test_get_rewards_empty(self, web3: Web3StakingModule):
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
    def test_get_rewards_okay(self, web3: Web3StakingModule, rewards_tree: RewardsTree):
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
    def test_get_rewards_unexpected_root(self, web3: Web3StakingModule, rewards_tree: RewardsTree):
        encoded_tree = rewards_tree.encode()
        web3.ipfs = Mock(fetch=Mock(return_value=encoded_tree))

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=HexBytes(b"DOES NOT MATCH"),
            strikes_tree_root=Mock(),
            rewards_tree_cid=CID("QmRT"),
            strikes_tree_cid=Mock(),
        )

        with pytest.raises(ValueError, match="tree root"):
            _ = last_report.rewards

        web3.ipfs.fetch.assert_called_once_with(last_report.rewards_tree_cid, FrameNumber(0))

    @pytest.mark.unit
    def test_get_strikes_empty(self, web3: Web3StakingModule):
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
    def test_get_strikes_okay(self, web3: Web3StakingModule, strikes_tree: StrikesTree):
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
    def test_get_strikes_unexpected_root(self, web3: Web3StakingModule, strikes_tree: StrikesTree):
        encoded_tree = strikes_tree.encode()
        web3.ipfs = Mock(fetch=Mock(return_value=encoded_tree))

        last_report = LastReport(
            w3=web3,
            blockstamp=Mock(),
            current_frame=FrameNumber(0),
            rewards_tree_root=Mock(),
            strikes_tree_root=HexBytes(b"DOES NOT MATCH"),
            rewards_tree_cid=Mock(),
            strikes_tree_cid=CID("QmRT"),
        )

        with pytest.raises(ValueError, match="tree root"):
            _ = last_report.strikes

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
