import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, NoReturn, cast
from unittest.mock import Mock, call, patch

import pytest
from eth_typing import HexAddress
from hexbytes import HexBytes

from src.constants import UINT64_MAX
from src.modules.common.types import ZERO_HASH, CurrentFrame, ModuleExecuteDelay
from src.modules.oracles.staking_modules.base import SMPerformanceOracle, SMPerformanceOracleError
from src.modules.oracles.staking_modules.common.distribution import Distribution
from src.modules.oracles.staking_modules.common.helpers.last_report import LastReport
from src.modules.oracles.staking_modules.common.log import Logs
from src.modules.oracles.staking_modules.common.state import DutyAccumulator
from src.modules.oracles.staking_modules.common.tree import RewardsTree, StrikesTree
from src.modules.oracles.staking_modules.common.types import StrikesList
from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from src.modules.sidecars.performance.common.db import Duty
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.execution.exceptions import InconsistentData
from src.providers.ipfs import CID
from src.types import EpochNumber, FrameNumber, Gwei, NodeOperatorId, SlotNumber, ValidatorIndex
from src.utils.types import hex_str_to_bytes
from src.utils.validator_state import is_active_validator
from src.web3py.extensions.telemetry_data_bus import TelemetryEventId
from src.web3py.types import Web3StakingModule
from tests.factory.blockstamp import BlockStampFactory, ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory


@pytest.fixture()
def module(web3):
    yield CSPerformanceOracle(web3)


@pytest.mark.unit
def test_init(module: CSPerformanceOracle):
    assert module


# Static functions you were dreaming of for so long.


def last_slot_of_epoch(epoch: int) -> int:
    return epoch * 32 + 31


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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("activation_epoch", "exit_epoch", "l_epoch", "r_epoch", "expected"),
    [
        pytest.param(0, 100, 10, 14, 5, id="active-for-whole-frame"),
        pytest.param(15, 100, 10, 14, 0, id="activates-after-frame"),
        pytest.param(0, 10, 10, 14, 0, id="exited-before-frame-start"),
        pytest.param(14, 100, 10, 14, 1, id="activates-on-frame-end"),
        pytest.param(12, 100, 10, 14, 3, id="activates-inside-frame"),
        pytest.param(0, 13, 10, 14, 3, id="exits-inside-frame"),
        pytest.param(12, 13, 10, 14, 1, id="active-for-one-epoch-inside-frame"),
        pytest.param(10, 11, 10, 10, 1, id="active-for-single-epoch-frame"),
        pytest.param(0, 10, 10, 10, 0, id="exited-at-single-epoch-frame"),
    ],
)
def test_count_active_epochs__activity_range_overlap__returns_active_epoch_count(
    activation_epoch: int,
    exit_epoch: int,
    l_epoch: int,
    r_epoch: int,
    expected: int,
):
    validator = make_validator(0, activation_epoch=activation_epoch, exit_epoch=exit_epoch)
    actual = SMPerformanceOracle._count_active_epochs(validator, EpochNumber(l_epoch), EpochNumber(r_epoch))
    assert actual == expected


@pytest.mark.unit
def test_count_active_epochs__compared_to_is_active_validator__matches_active_epoch_predicate():
    for activation_epoch in range(0, 8):
        for exit_epoch in range(activation_epoch, 10):
            validator = make_validator(0, activation_epoch=activation_epoch, exit_epoch=exit_epoch)

            for l_epoch in range(0, 8):
                for r_epoch in range(l_epoch, 8):
                    actual = SMPerformanceOracle._count_active_epochs(
                        validator, EpochNumber(l_epoch), EpochNumber(r_epoch)
                    )
                    expected = sum(
                        is_active_validator(validator, EpochNumber(epoch)) for epoch in range(l_epoch, r_epoch + 1)
                    )
                    assert actual == expected


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
    initial_epoch: int
    last_processing_ref_slot: int
    blockstamp_slot: int
    expected_frame: tuple[int, int] | type[Exception]


@pytest.mark.parametrize(
    "param",
    [
        pytest.param(
            FrameTestParam(
                epochs_per_frame=0,
                initial_epoch=FAR_FUTURE_EPOCH,
                last_processing_ref_slot=0,
                blockstamp_slot=0,
                expected_frame=ValueError,
            ),
            id="initial_epoch_not_set",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=1575,
                initial_epoch=63055,
                last_processing_ref_slot=2168959,
                blockstamp_slot=2219359,
                expected_frame=(67780, 69354),
            ),
            id="holesky_testnet",
        ),
        # NOTE: Impossible case in current processing
        # pytest.param(
        #     FrameTestParam(
        #         epochs_per_frame=32,
        #         initial_epoch=101,
        #         last_processing_ref_slot=0,
        #         blockstamp_slot=0,
        #         expected_frame=(69, 100),
        #     ),
        #     id="not_yet_reached_initial_epoch",
        # ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=101,
                last_processing_ref_slot=0,
                blockstamp_slot=last_slot_of_epoch(164),
                expected_frame=(69, 164),
            ),
            id="first_report_with_missed_frames",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=101,
                last_processing_ref_slot=0,
                blockstamp_slot=last_slot_of_epoch(100),
                expected_frame=(69, 100),
            ),
            id="frame_0",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=101,
                last_processing_ref_slot=last_slot_of_epoch(100),
                blockstamp_slot=last_slot_of_epoch(124),
                expected_frame=(101, 132),
            ),
            id="frame_1_before_ref_slot",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=101,
                last_processing_ref_slot=last_slot_of_epoch(100),
                blockstamp_slot=last_slot_of_epoch(132),
                expected_frame=(101, 132),
            ),
            id="frame_1",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=101,
                last_processing_ref_slot=last_slot_of_epoch(132),
                blockstamp_slot=last_slot_of_epoch(196),
                expected_frame=(133, 196),
            ),
            id="one_frame_missed",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=101,
                last_processing_ref_slot=last_slot_of_epoch(90),
                blockstamp_slot=last_slot_of_epoch(132),
                expected_frame=(91, 132),
            ),
            id="initial_epoch_moved_forward_with_missed_frame",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=32,
                initial_epoch=11,
                last_processing_ref_slot=last_slot_of_epoch(20),
                blockstamp_slot=last_slot_of_epoch(15),
                expected_frame=InconsistentData,
            ),
            id="last_processing_ref_slot_in_future",
        ),
        pytest.param(
            FrameTestParam(
                epochs_per_frame=4,
                initial_epoch=2,
                last_processing_ref_slot=0,
                blockstamp_slot=last_slot_of_epoch(1),
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
            initial_epoch=param.initial_epoch,
            epochs_per_frame=param.epochs_per_frame,
            fast_lane_length_slots=...,
        )
    )

    module.w3.staking_module.get_last_processing_ref_slot = Mock(return_value=param.last_processing_ref_slot)
    module.get_initial_ref_slot = Mock(return_value=last_slot_of_epoch(param.initial_epoch - 1))

    bs = BlockStampFactory.build(slot_number=param.blockstamp_slot)
    if isinstance(param.expected_frame, type) and issubclass(param.expected_frame, Exception):
        with pytest.raises(param.expected_frame):
            l_epoch = module._get_l_epoch(bs)
            module._predict_r_epoch(bs)
    else:
        l_epoch = module._get_l_epoch(bs)
        r_epoch = module._predict_r_epoch(bs)
        assert (l_epoch, r_epoch) == param.expected_frame


@pytest.mark.unit
@pytest.mark.parametrize(
    ("finalized_epoch", "predicted_ref_epoch", "report_ref_epoch"),
    [
        pytest.param(
            EpochNumber(124),
            EpochNumber(132),
            None,
            id="before_report_ref_slot_prediction_reaches_frame_end",
        ),
        pytest.param(
            EpochNumber(132),
            EpochNumber(132),
            EpochNumber(132),
            id="at_report_ref_slot_prediction_matches_report_range",
        ),
        pytest.param(
            EpochNumber(133),
            EpochNumber(164),
            EpochNumber(132),
            id="after_report_ref_slot_prediction_still_covers_report_range",
        ),
    ],
)
def test_predicted_range__relative_to_finalized_and_report_ref_epoch(
    module: CSPerformanceOracle,
    mock_chain_config: NoReturn,
    finalized_epoch: EpochNumber,
    predicted_ref_epoch: EpochNumber,
    report_ref_epoch: EpochNumber | None,
):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=101,
            epochs_per_frame=32,
            fast_lane_length_slots=...,
        )
    )
    module.w3.staking_module.get_last_processing_ref_slot = Mock(return_value=last_slot_of_epoch(100))

    finalized_blockstamp = BlockStampFactory.build(slot_number=last_slot_of_epoch(finalized_epoch))
    predicted_l_epoch, predicted_r_epoch = module._get_predicted_range(finalized_blockstamp)

    assert predicted_r_epoch == predicted_ref_epoch
    assert predicted_r_epoch >= finalized_epoch

    if report_ref_epoch is None:
        return

    report_blockstamp = ReferenceBlockStampFactory.build(
        slot_number=last_slot_of_epoch(report_ref_epoch),
        ref_slot=last_slot_of_epoch(report_ref_epoch),
        ref_epoch=report_ref_epoch,
    )
    report_l_epoch, report_r_epoch = module._get_report_range(report_blockstamp)

    assert predicted_l_epoch == report_l_epoch
    assert report_r_epoch == report_ref_epoch
    assert predicted_r_epoch >= report_r_epoch


@pytest.mark.unit
def test_predict_r_epoch__frame_starts_at_initial_epoch__returns_inclusive_frame_end(
    module: CSPerformanceOracle, mock_chain_config: NoReturn
):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=95104,
            epochs_per_frame=8,
            fast_lane_length_slots=...,
        )
    )
    module.w3.staking_module.get_last_processing_ref_slot = Mock(return_value=last_slot_of_epoch(95103))

    blockstamp = BlockStampFactory.build(slot_number=last_slot_of_epoch(95110))

    l_epoch = module._get_l_epoch(blockstamp)
    r_epoch = module._predict_r_epoch(blockstamp)

    assert (l_epoch, r_epoch) == (EpochNumber(95104), EpochNumber(95111))


@pytest.mark.unit
def test_execute_module_pushes_predicted_epochs_demand(module: CSPerformanceOracle, mock_chain_config: NoReturn):
    blockstamp = ReferenceBlockStampFactory.build()
    module._check_compatibility = Mock(return_value=True)
    module.push_epochs_demand = Mock()
    module.get_blockstamp_for_report = Mock(return_value=None)

    execute_delay = module.execute_module(blockstamp)

    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    module.push_epochs_demand.assert_called_once_with(blockstamp)


@pytest.mark.unit
def test_push_epochs_demand_skips_demand_post_when_range_available(module: CSPerformanceOracle):
    blockstamp = BlockStampFactory.build()
    module.w3 = Mock()
    module._get_l_epoch = Mock(return_value=EpochNumber(10))
    module._predict_r_epoch = Mock(return_value=EpochNumber(20))
    module._check_range_availability = Mock(return_value=True)
    module.w3.performance.get_epochs_demand = Mock()
    module.w3.performance.post_epochs_demand = Mock()

    module.push_epochs_demand(blockstamp)

    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._predict_r_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(10), EpochNumber(20))
    module.w3.performance.get_epochs_demand.assert_not_called()
    module.w3.performance.post_epochs_demand.assert_not_called()


@pytest.mark.unit
def test_push_epochs_demand_skips_demand_post_when_demand_same(module: CSPerformanceOracle):
    blockstamp = BlockStampFactory.build()
    module.w3 = Mock()
    module._get_l_epoch = Mock(return_value=EpochNumber(10))
    module._predict_r_epoch = Mock(return_value=EpochNumber(20))
    module._check_range_availability = Mock(return_value=False)
    demand = Mock(from_epoch=EpochNumber(10), to_epoch=EpochNumber(20))
    module.w3.performance.get_epochs_demand = Mock(return_value=demand)
    module.w3.performance.post_epochs_demand = Mock()

    module.push_epochs_demand(blockstamp)

    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._predict_r_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(10), EpochNumber(20))
    module.w3.performance.get_epochs_demand.assert_called_once_with(module.consumer)
    module.w3.performance.post_epochs_demand.assert_not_called()


@pytest.mark.unit
def test_push_epochs_demand_posts_new_demand_when_range_not_available(module: CSPerformanceOracle):
    blockstamp = BlockStampFactory.build()
    module.w3 = Mock()
    module._get_l_epoch = Mock(return_value=EpochNumber(10))
    module._predict_r_epoch = Mock(return_value=EpochNumber(20))
    module._check_range_availability = Mock(return_value=False)
    module.w3.performance.get_epochs_demand = Mock(return_value=None)
    module.w3.performance.post_epochs_demand = Mock()

    module.push_epochs_demand(blockstamp)

    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._predict_r_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(10), EpochNumber(20))
    module.w3.performance.get_epochs_demand.assert_called_once_with(module.consumer)
    module.w3.performance.post_epochs_demand.assert_called_once_with(module.consumer, EpochNumber(10), EpochNumber(20))


@pytest.mark.unit
def test_check_report_range_availability__uses_report_ref_epoch(module: CSPerformanceOracle):
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=12)
    module._get_l_epoch = Mock(return_value=EpochNumber(10))
    module._check_range_availability = Mock(return_value=True)

    result = module.check_report_range_availability(blockstamp)

    assert result is True
    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(10), EpochNumber(12))


@pytest.mark.unit
def test_refresh_contracts_deletes_old_demand_when_address_changes(module: CSPerformanceOracle):
    old_consumer = module.consumer
    new_consumer = cast(HexAddress, "0x00000000000000000000000000000000000000bb")

    new_oracle = Mock(address=new_consumer)
    module.w3 = Mock()
    module.w3.staking_module.reload_contracts = Mock()
    module.w3.staking_module.oracle = new_oracle
    module.w3.performance.delete_epochs_demand = Mock()

    module.refresh_contracts()

    module.w3.staking_module.reload_contracts.assert_called_once()
    module.w3.performance.delete_epochs_demand.assert_called_once_with(old_consumer)
    assert module.report_contract is new_oracle
    assert module.consumer == new_consumer


@pytest.mark.unit
def test_refresh_contracts_keeps_demand_when_address_unchanged(module: CSPerformanceOracle):
    same_consumer = module.consumer

    same_oracle = Mock(address=same_consumer)
    module.w3 = Mock()
    module.w3.staking_module.reload_contracts = Mock()
    module.w3.staking_module.oracle = same_oracle
    module.w3.performance.delete_epochs_demand = Mock()

    module.refresh_contracts()

    module.w3.performance.delete_epochs_demand.assert_not_called()
    assert module.consumer == same_consumer


@pytest.mark.unit
def test_check_range_availability_sends_initial_diagnostic(module: CSPerformanceOracle):
    module.w3 = Mock()
    module.w3.performance.is_range_available = Mock(return_value=False)
    module.w3.performance.get_stored_epochs_count = Mock(return_value=3)
    module.collector_telemetry.send_callback = Mock(return_value=True)
    module.collector_telemetry.interval_seconds = 60

    with patch.object(time, 'monotonic', return_value=1000.0):
        result = module._check_range_availability(EpochNumber(10), EpochNumber(20))

    assert result is False
    module.collector_telemetry.send_callback.assert_called_once_with(
        TelemetryEventId.DIAGNOSTIC,
        {
            "l_epoch": 10,
            "r_epoch": 20,
            "ready": 3,
        },
    )


@pytest.mark.unit
def test_check_range_availability_skips_same_payload_even_after_interval(module: CSPerformanceOracle):
    module.w3 = Mock()
    module.w3.performance.is_range_available = Mock(return_value=False)
    module.w3.performance.get_stored_epochs_count = Mock(return_value=3)
    module.collector_telemetry.send_callback = Mock(return_value=True)
    module.collector_telemetry.interval_seconds = 60

    with patch.object(time, 'monotonic', side_effect=[1000.0, 1061.0]):
        module._check_range_availability(EpochNumber(10), EpochNumber(20))
        module._check_range_availability(EpochNumber(10), EpochNumber(20))

    module.collector_telemetry.send_callback.assert_called_once()
    assert module.w3.performance.get_stored_epochs_count.call_count == 2


@pytest.mark.unit
def test_check_range_availability_sends_changed_payload_when_ready(module: CSPerformanceOracle):
    module.w3 = Mock()
    # first call: 3 out of 11 epochs ready → not available → normal cooldown applies
    # second call: all 11 epochs ready → range_available=True → ignore_cooldown=True → sent despite short gap
    module.w3.performance.get_stored_epochs_count = Mock(side_effect=[3, 11])
    module.collector_telemetry.send_callback = Mock(return_value=True)
    module.collector_telemetry.interval_seconds = 60

    with patch.object(time, 'monotonic', side_effect=[1000.0, 1001.0, 1001.0]):
        module._check_range_availability(EpochNumber(10), EpochNumber(20))
        module._check_range_availability(EpochNumber(10), EpochNumber(20))

    assert module.collector_telemetry.send_callback.call_count == 2
    assert module.collector_telemetry.send_callback.call_args_list[1] == call(
        TelemetryEventId.DIAGNOSTIC,
        {
            "l_epoch": 10,
            "r_epoch": 20,
            "ready": 11,
        },
    )


@pytest.mark.unit
def test_check_range_availability_retries_same_payload_if_previous_send_failed(module: CSPerformanceOracle):
    module.w3 = Mock()
    # stored == needed (11 epochs: 10..20 inclusive) → range is available → result=True
    module.w3.performance.get_stored_epochs_count = Mock(return_value=11)
    module.collector_telemetry.send_callback = Mock(side_effect=[False, True])
    module.collector_telemetry.interval_seconds = 60

    first_result = module._check_range_availability(EpochNumber(10), EpochNumber(20))
    second_result = module._check_range_availability(EpochNumber(10), EpochNumber(20))

    assert first_result is True
    assert second_result is True
    assert module.collector_telemetry.send_callback.call_count == 2


@pytest.fixture()
def mock_frame_config(module: CSPerformanceOracle):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=0,
            epochs_per_frame=32,
            fast_lane_length_slots=...,
        )
    )


@pytest.mark.unit
def test_prepare_duties_state__range_not_available__raises_error(
    module: CSPerformanceOracle, mock_chain_config: NoReturn, mock_frame_config: NoReturn
):
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=12)
    module._get_l_epoch = Mock(return_value=EpochNumber(10))
    module._check_range_availability = Mock(return_value=False)
    module._get_duties_state = Mock()

    with pytest.raises(ValueError, match="Performance data range is not available yet"):
        module._prepare_duties_state(blockstamp)

    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(10), EpochNumber(12))
    module._get_duties_state.assert_not_called()


@pytest.mark.unit
def test_prepare_duties_state__returns_duties_state_for_ref_epoch_range(
    module: CSPerformanceOracle, mock_chain_config: NoReturn, mock_frame_config: NoReturn
):
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=12)
    state = Mock()
    module._get_l_epoch = Mock(return_value=EpochNumber(10))
    module._check_range_availability = Mock(return_value=True)
    module._get_web3_converter = Mock(return_value=Mock(frame_config=Mock(epochs_per_frame=4)))
    module._get_duties_state = Mock(return_value=state)

    result = module._prepare_duties_state(blockstamp)

    assert result is state
    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(10), EpochNumber(12))
    module._get_duties_state.assert_called_once_with(EpochNumber(10), EpochNumber(12), 4)


@pytest.mark.unit
def test_get_duties_state__build_error__does_not_cache_result(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(side_effect=[ValueError("first"), ValueError("second")])

    with pytest.raises(ValueError, match="first"):
        module._get_duties_state(EpochNumber(0), EpochNumber(0), 1)

    with pytest.raises(ValueError, match="second"):
        module._get_duties_state(EpochNumber(0), EpochNumber(0), 1)

    assert module._receive_last_finalized_slot.call_count == 2


@pytest.mark.unit
def test_get_duties_state__epochs_data_received__stores_frame_duties(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator_a = make_validator(0, activation_epoch=0, exit_epoch=10)
    validator_b = make_validator(1, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(
        return_value={validator_a.index: validator_a, validator_b.index: validator_b}
    )

    epochs_data = [
        Duty(
            epoch=0,
            missed_attestation_vids=[validator_a.index],
            proposals_vids=[int(validator_a.index), int(validator_b.index)],
            proposals_flags=[True, False],
            syncs_vids=[int(validator_a.index), int(validator_b.index)],
            syncs_misses=[0, 1],
        ),
        Duty(
            epoch=1,
            missed_attestation_vids=[],
            proposals_vids=[int(validator_b.index), int(validator_a.index), int(validator_b.index)],
            proposals_flags=[True, True, True],
            syncs_vids=[int(validator_a.index), int(validator_b.index)],
            syncs_misses=[2, 3],
        ),
    ]
    module.w3.performance.get_epochs_data = Mock(return_value=epochs_data)
    frame = (EpochNumber(0), EpochNumber(1))

    state = module._get_duties_state(EpochNumber(0), EpochNumber(1), epochs_per_frame=2)

    module._receive_last_finalized_slot.assert_called_once()
    module.w3.cc.get_validators_by_indexes.assert_called_once_with("finalized")

    module.w3.performance.get_epochs_data.assert_called_once_with(EpochNumber(0), EpochNumber(1))
    frame_data = state.data[frame]
    assert frame_data.attestations == {
        validator_a.index: DutyAccumulator(assigned=2, included=1),
        validator_b.index: DutyAccumulator(assigned=2, included=2),
    }
    assert frame_data.proposals == {
        validator_a.index: DutyAccumulator(assigned=2, included=2),
        validator_b.index: DutyAccumulator(assigned=3, included=2),
    }
    assert frame_data.syncs == {
        validator_a.index: DutyAccumulator(assigned=4, included=2),
        validator_b.index: DutyAccumulator(assigned=4, included=0),
    }


@pytest.mark.unit
def test_get_duties_state__missed_attestation_for_inactive_validator__raises_error(module: CSPerformanceOracle):
    inactive_validator = make_validator(5, activation_epoch=10, exit_epoch=20)
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={inactive_validator.index: inactive_validator})
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                missed_attestation_vids=[inactive_validator.index],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
    )

    with pytest.raises(ValueError, match="not active"):
        module._get_duties_state(EpochNumber(0), EpochNumber(0), epochs_per_frame=1)

    module.w3.performance.get_epochs_data.assert_called_once_with(EpochNumber(0), EpochNumber(0))


@pytest.mark.unit
@pytest.mark.parametrize(
    "duty",
    [
        pytest.param(
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[999],
                proposals_flags=[True],
                syncs_vids=[],
                syncs_misses=[],
            ),
            id="unknown-proposer",
        ),
        pytest.param(
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[0],
                proposals_flags=[True],
                syncs_vids=[999],
                syncs_misses=[0],
            ),
            id="unknown-sync-committee-member",
        ),
    ],
)
def test_get_duties_state__duty_for_unknown_validator__raises_error(
    module: CSPerformanceOracle,
    duty: Duty,
):
    module._receive_last_finalized_slot = Mock(return_value=Mock(slot_number=123))
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(return_value=[duty])

    with pytest.raises(ValueError, match="is missing in validators"):
        module._get_duties_state(EpochNumber(0), EpochNumber(0), epochs_per_frame=1)

    module.w3.performance.get_epochs_data.assert_called_once_with(EpochNumber(0), EpochNumber(0))


@pytest.mark.unit
def test_get_duties_state__sync_misses_exceed_blocks_in_epoch__raises_error(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[int(validator.index)],
                proposals_flags=[True],
                syncs_vids=[int(validator.index)],
                syncs_misses=[2],
            ),
        ]
    )

    with pytest.raises(ValueError, match="Inconsistent sync committee duties data"):
        module._get_duties_state(EpochNumber(0), EpochNumber(0), epochs_per_frame=1)

    module.w3.performance.get_epochs_data.assert_called_once_with(EpochNumber(0), EpochNumber(0))


@pytest.mark.unit
def test_get_duties_state__validators_active_for_part_of_frame__stores_only_active_duties(
    module: CSPerformanceOracle,
):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    active_all = make_validator(0, activation_epoch=0, exit_epoch=10)
    active_late = make_validator(1, activation_epoch=1, exit_epoch=10)
    exit_early = make_validator(2, activation_epoch=0, exit_epoch=1)
    inactive_all = make_validator(3, activation_epoch=10, exit_epoch=20)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(
        return_value={v.index: v for v in [active_all, active_late, exit_early, inactive_all]}
    )
    epochs_data = [
        Duty(
            epoch=0,
            missed_attestation_vids=[exit_early.index],
            proposals_vids=[int(active_all.index)],
            proposals_flags=[True],
            syncs_vids=[int(active_all.index)],
            syncs_misses=[0],
        ),
        Duty(
            epoch=1,
            missed_attestation_vids=[active_all.index],
            proposals_vids=[int(active_late.index), int(active_all.index)],
            proposals_flags=[True, False],
            syncs_vids=[int(active_all.index), int(active_late.index)],
            syncs_misses=[1, 0],
        ),
        Duty(
            epoch=2,
            missed_attestation_vids=[],
            proposals_vids=[int(active_all.index)],
            proposals_flags=[True],
            syncs_vids=[int(active_all.index)],
            syncs_misses=[1],
        ),
    ]
    module.w3.performance.get_epochs_data = Mock(return_value=epochs_data)

    state = module._get_duties_state(EpochNumber(0), EpochNumber(2), epochs_per_frame=3)

    module.w3.performance.get_epochs_data.assert_called_once_with(EpochNumber(0), EpochNumber(2))
    frame_data = state.data[(EpochNumber(0), EpochNumber(2))]
    assert frame_data.attestations == {
        active_all.index: DutyAccumulator(assigned=3, included=2),
        active_late.index: DutyAccumulator(assigned=2, included=2),
        exit_early.index: DutyAccumulator(assigned=1, included=0),
    }
    assert frame_data.proposals == {
        active_all.index: DutyAccumulator(assigned=3, included=2),
        active_late.index: DutyAccumulator(assigned=1, included=1),
    }
    assert frame_data.syncs == {
        active_all.index: DutyAccumulator(assigned=3, included=1),
        active_late.index: DutyAccumulator(assigned=1, included=1),
    }


@pytest.mark.unit
def test_get_duties_state__duplicate_epoch_data__raises_error(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
    )

    with pytest.raises(ValueError, match="Duplicate epoch data"):
        module._get_duties_state(EpochNumber(0), EpochNumber(1), epochs_per_frame=2)


@pytest.mark.unit
def test_get_duties_state__incomplete_frame_data__raises_error(module: CSPerformanceOracle):
    """Frame expects 2 epochs but only 1 is returned."""
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
    )

    with pytest.raises(ValueError, match="Invalid frame data"):
        module._get_duties_state(EpochNumber(0), EpochNumber(1), epochs_per_frame=2)


@pytest.mark.unit
def test_validate_epoch_data__valid_data__does_not_raise():
    duty = Duty(
        epoch=0,
        missed_attestation_vids=[1, 2, 3],
        proposals_vids=[4, 5],
        proposals_flags=[True, False],
        syncs_vids=[6, 7],
        syncs_misses=[0, 1],
    )
    SMPerformanceOracle._validate_epoch_data(duty)


@pytest.mark.unit
def test_validate_epoch_data__duplicate_missed_attestation_vids__raises_error():
    duty = Duty(
        epoch=0,
        missed_attestation_vids=[1, 1],  # duplicate
        proposals_vids=[],
        proposals_flags=[],
        syncs_vids=[],
        syncs_misses=[],
    )

    with pytest.raises(ValueError, match="Duplicate validator indices in missed attestation vids"):
        SMPerformanceOracle._validate_epoch_data(duty)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("proposals_vids", "proposals_flags", "syncs_vids", "syncs_misses", "match"),
    [
        pytest.param(
            [0],
            [True, False],
            [],
            [],
            "corrupted",
            id="proposals-flags-length-mismatch",
        ),
        pytest.param(
            [],
            [],
            [0],
            [0, 1],
            "corrupted",
            id="syncs-misses-length-mismatch",
        ),
    ],
)
def test_validate_epoch_data__length_mismatch__raises_error(
    proposals_vids: list,
    proposals_flags: list,
    syncs_vids: list,
    syncs_misses: list,
    match: str,
):
    duty = Duty(
        epoch=0,
        missed_attestation_vids=[],
        proposals_vids=proposals_vids,
        proposals_flags=proposals_flags,
        syncs_vids=syncs_vids,
        syncs_misses=syncs_misses,
    )

    with pytest.raises(ValueError, match=match):
        SMPerformanceOracle._validate_epoch_data(duty)


@pytest.mark.unit
def test_get_duties_state__missed_attestation_for_unknown_validator__raises_error(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value=Mock(slot_number=123))
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                missed_attestation_vids=[999],  # unknown
                proposals_vids=[],
                proposals_flags=[],
                syncs_vids=[],
                syncs_misses=[],
            ),
        ]
    )

    with pytest.raises(ValueError, match="is missing in validators"):
        module._get_duties_state(EpochNumber(0), EpochNumber(0), epochs_per_frame=1)


@pytest.mark.unit
def test_get_duties_state__multi_frame__each_frame_fetched_independently(module: CSPerformanceOracle):
    """Два фрейма: get_epochs_data вызывается отдельно для каждого, результаты пишутся в правильные фреймы."""
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(
        side_effect=[
            # frame 0..0
            [
                Duty(
                    epoch=0,
                    missed_attestation_vids=[],
                    proposals_vids=[],
                    proposals_flags=[],
                    syncs_vids=[],
                    syncs_misses=[],
                )
            ],
            # frame 1..1
            [
                Duty(
                    epoch=1,
                    missed_attestation_vids=[validator.index],
                    proposals_vids=[],
                    proposals_flags=[],
                    syncs_vids=[],
                    syncs_misses=[],
                )
            ],
        ]
    )

    state = module._get_duties_state(EpochNumber(0), EpochNumber(1), epochs_per_frame=1)

    assert module.w3.performance.get_epochs_data.call_count == 2
    module.w3.performance.get_epochs_data.assert_any_call(EpochNumber(0), EpochNumber(0))
    module.w3.performance.get_epochs_data.assert_any_call(EpochNumber(1), EpochNumber(1))

    frame0_atts = state.data[(EpochNumber(0), EpochNumber(0))].attestations
    frame1_atts = state.data[(EpochNumber(1), EpochNumber(1))].attestations
    assert frame0_atts[validator.index] == DutyAccumulator(assigned=1, included=1)
    assert frame1_atts[validator.index] == DutyAccumulator(assigned=1, included=0)


@pytest.mark.unit
def test_get_duties_state__no_blocks_in_epoch__sync_duties_not_recorded(module: CSPerformanceOracle):
    module._receive_last_finalized_slot = Mock(return_value="finalized")
    validator = make_validator(0, activation_epoch=0, exit_epoch=10)
    module.w3 = Mock()
    module.w3.cc.get_validators_by_indexes = Mock(return_value={validator.index: validator})
    module.w3.performance.get_epochs_data = Mock(
        return_value=[
            Duty(
                epoch=0,
                missed_attestation_vids=[],
                proposals_vids=[int(validator.index)],
                proposals_flags=[False],  # блок предложен, но не включён
                syncs_vids=[int(validator.index)],
                syncs_misses=[0],
            ),
        ]
    )

    state = module._get_duties_state(EpochNumber(0), EpochNumber(0), epochs_per_frame=1)

    frame_data = state.data[(EpochNumber(0), EpochNumber(0))]
    assert frame_data.proposals[validator.index] == DutyAccumulator(assigned=1, included=0)
    assert validator.index not in frame_data.syncs  # sync не записан


@pytest.mark.unit
def test_get_predicted_range__l_epoch_exceeds_r_epoch__raises_error(
    module: CSPerformanceOracle, mock_chain_config: NoReturn
):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=101,
            epochs_per_frame=32,
            fast_lane_length_slots=...,
        )
    )
    # last_processing_ref_slot > blockstamp → _get_l_epoch returns epoch > r_epoch
    module.w3.staking_module.get_last_processing_ref_slot = Mock(return_value=last_slot_of_epoch(200))
    module._get_l_epoch = Mock(return_value=EpochNumber(200))
    module._predict_r_epoch = Mock(return_value=EpochNumber(100))

    bs = BlockStampFactory.build(slot_number=last_slot_of_epoch(100))
    with pytest.raises(SMPerformanceOracleError, match="invalid predicted epochs range"):
        module._get_predicted_range(bs)


@pytest.mark.unit
def test_get_report_range__l_epoch_exceeds_r_epoch__raises_error(
    module: CSPerformanceOracle, mock_chain_config: NoReturn
):
    module.get_frame_config = Mock(
        return_value=FrameConfigFactory.build(
            initial_epoch=101,
            epochs_per_frame=32,
            fast_lane_length_slots=...,
        )
    )
    module._get_l_epoch = Mock(return_value=EpochNumber(200))

    bs = ReferenceBlockStampFactory.build(ref_epoch=EpochNumber(100))
    with pytest.raises(SMPerformanceOracleError, match="invalid report epochs range"):
        module._get_report_range(bs)


@pytest.mark.unit
def test_prepare_duties_state__right_bound__uses_ref_epoch(module: CSPerformanceOracle):
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=123)
    state = Mock()
    module._get_l_epoch = Mock(return_value=EpochNumber(5))
    module._check_range_availability = Mock(return_value=True)
    module._get_web3_converter = Mock(return_value=Mock(frame_config=Mock(epochs_per_frame=4)))
    module._get_duties_state = Mock(return_value=state)

    result = module._prepare_duties_state(blockstamp)

    assert result is state
    module._get_l_epoch.assert_called_once_with(blockstamp)
    module._check_range_availability.assert_called_once_with(EpochNumber(5), EpochNumber(123))
    module._get_duties_state.assert_called_once_with(EpochNumber(5), EpochNumber(123), 4)


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
        pytest.param(
            BuildReportTestParam(
                last_report=Mock(
                    rewards_tree_root=HexBytes(b"OLD_TREE_ROOT"),
                    rewards_tree_cid=CID("QmOLD_TREE"),
                    rewards=[(NodeOperatorId(0), 100)],
                    strikes_tree_root=HexBytes(b"OLD_STRIKES_ROOT"),
                    strikes_tree_cid=CID("QmOLD_STRIKES"),
                    strikes={},
                ),
                curr_distribution=Mock(
                    return_value=Mock(
                        spec=Distribution,
                        total_rewards=5,
                        total_rewards_map=defaultdict(int, {NodeOperatorId(0): 5}),
                        total_rebate=1,
                        strikes={
                            (NodeOperatorId(0), HexBytes(b"0x00")): StrikesList([1]),
                        },
                        logs=Logs(frames=[Mock()]),
                    )
                ),
                curr_rewards_tree_root=HexBytes(b"NEW_TREE_ROOT"),
                curr_rewards_tree_cid=CID("QmNEW_TREE"),
                curr_strikes_tree_root=HexBytes(b"NEW_STRIKES_ROOT"),
                curr_strikes_tree_cid=CID("QmNEW_STRIKES"),
                curr_log_cid=CID("QmLOG"),
                expected_make_rewards_tree_call_args=(({NodeOperatorId(0): 5},),),
                expected_func_result=(
                    1,
                    100500,
                    HexBytes(b"NEW_TREE_ROOT"),
                    CID("QmNEW_TREE"),
                    CID("QmLOG"),
                    5,
                    1,
                    HexBytes(b"NEW_STRIKES_ROOT"),
                    CID("QmNEW_STRIKES"),
                ),
            ),
            id="new_strikes_tree_published",
        ),
        pytest.param(
            BuildReportTestParam(
                last_report=Mock(
                    rewards_tree_root=HexBytes(b"OLD_TREE_ROOT"),
                    rewards_tree_cid=CID("QmOLD_TREE"),
                    rewards=[(NodeOperatorId(0), 100)],
                    strikes_tree_root=HexBytes(b"SAME_STRIKES_ROOT"),
                    strikes_tree_cid=CID("QmOLD_STRIKES"),
                    strikes={},
                ),
                curr_distribution=Mock(
                    return_value=Mock(
                        spec=Distribution,
                        total_rewards=5,
                        total_rewards_map=defaultdict(int, {NodeOperatorId(0): 5}),
                        total_rebate=1,
                        strikes={
                            (NodeOperatorId(0), HexBytes(b"0x00")): StrikesList([1]),
                        },
                        logs=Logs(frames=[Mock()]),
                    )
                ),
                curr_rewards_tree_root=HexBytes(b"NEW_TREE_ROOT"),
                curr_rewards_tree_cid=CID("QmNEW_TREE"),
                curr_strikes_tree_root=HexBytes(b"SAME_STRIKES_ROOT"),
                curr_strikes_tree_cid=CID("QmOLD_STRIKES"),
                curr_log_cid=CID("QmLOG"),
                expected_make_rewards_tree_call_args=(({NodeOperatorId(0): 5},),),
                expected_func_result=(
                    1,
                    100500,
                    HexBytes(b"NEW_TREE_ROOT"),
                    CID("QmNEW_TREE"),
                    CID("QmLOG"),
                    5,
                    1,
                    HexBytes(b"SAME_STRIKES_ROOT"),
                    CID("QmOLD_STRIKES"),
                ),
            ),
            id="same_strikes_tree_reuses_cid",
        ),
    ],
)
@pytest.mark.unit
def test_build_report(module: CSPerformanceOracle, param: BuildReportTestParam):
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


@pytest.mark.unit
def test_build_report_raises_on_inconsistent_strikes_tree(module: CSPerformanceOracle):
    """Strikes CID matches last report but root differs — should raise ValueError."""
    last_report = Mock(
        rewards_tree_root=HexBytes(ZERO_HASH),
        rewards_tree_cid=None,
        rewards=[],
        strikes_tree_root=HexBytes(b"OLD_STRIKES_ROOT"),
        strikes_tree_cid=CID("QmOLD_STRIKES"),
        strikes={},
    )
    distribution = Mock(
        spec=Distribution,
        total_rewards=0,
        total_rewards_map=defaultdict(int),
        total_rebate=0,
        strikes={
            (NodeOperatorId(0), HexBytes(b"0x00")): StrikesList([1]),
        },
        logs=Logs(frames=[Mock()]),
    )

    module.report_contract.get_consensus_version = Mock(return_value=1)
    module._calculate_distribution = Mock(return_value=(distribution, last_report))
    module._make_rewards_tree = Mock()
    module._make_strikes_tree = Mock(return_value=Mock(root=HexBytes(b"DIFFERENT_ROOT")))
    # _publish_tree returns CID that matches last report's strikes CID, but root differs
    module._publish_tree = Mock(return_value=CID("QmOLD_STRIKES"))
    module._publish_log = Mock(return_value=CID("QmLOG"))

    with pytest.raises(ValueError, match="Invalid strikes tree built"):
        module.build_report(Mock(ref_slot=100500))


@pytest.mark.unit
def test_execute_module_not_collected(module: CSPerformanceOracle):
    module._check_compatibility = Mock(return_value=True)
    report_blockstamp = Mock(slot_number=100500, ref_epoch=EpochNumber(12))
    module.get_blockstamp_for_report = Mock(return_value=report_blockstamp)
    module.push_epochs_demand = Mock()
    module.check_report_range_availability = Mock(return_value=False)
    module.process_report = Mock()

    last_finalized_blockstamp = Mock(slot_number=100500)
    execute_delay = module.execute_module(last_finalized_blockstamp=last_finalized_blockstamp)

    module.push_epochs_demand.assert_called_once_with(last_finalized_blockstamp)
    module.check_report_range_availability.assert_called_once_with(report_blockstamp)
    module.process_report.assert_not_called()
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH


@pytest.mark.unit
def test_execute_module_skips_collecting_if_not_compatible(module: CSPerformanceOracle):
    module._check_compatibility = Mock(return_value=False)
    module.push_epochs_demand = Mock()

    execute_delay = module.execute_module(last_finalized_blockstamp=Mock(slot_number=100500))

    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH
    module.push_epochs_demand.assert_not_called()


@pytest.mark.unit
def test_execute_module_no_report_blockstamp(module: CSPerformanceOracle):
    module._check_compatibility = Mock(return_value=True)
    module.get_blockstamp_for_report = Mock(return_value=None)
    module.push_epochs_demand = Mock()
    module.check_report_range_availability = Mock()
    module.process_report = Mock()

    last_finalized_blockstamp = Mock(slot_number=100500)
    execute_delay = module.execute_module(last_finalized_blockstamp=last_finalized_blockstamp)

    module.push_epochs_demand.assert_called_once_with(last_finalized_blockstamp)
    module.check_report_range_availability.assert_not_called()
    module.process_report.assert_not_called()
    assert execute_delay is ModuleExecuteDelay.NEXT_FINALIZED_EPOCH


@pytest.mark.unit
def test_execute_module_processed(module: CSPerformanceOracle):
    report_blockstamp = Mock(slot_number=100500, ref_epoch=EpochNumber(12))
    module.get_blockstamp_for_report = Mock(return_value=report_blockstamp)
    module.process_report = Mock()
    module._check_compatibility = Mock(return_value=True)
    module.push_epochs_demand = Mock()
    module.check_report_range_availability = Mock(return_value=True)

    last_finalized_blockstamp = Mock(slot_number=100500)
    execute_delay = module.execute_module(last_finalized_blockstamp=last_finalized_blockstamp)

    module.push_epochs_demand.assert_called_once_with(last_finalized_blockstamp)
    module.check_report_range_availability.assert_called_once_with(report_blockstamp)
    module.process_report.assert_called_once_with(report_blockstamp)
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

        state = Mock()
        module._prepare_duties_state = Mock(return_value=state)
        module._get_web3_converter = Mock(return_value=Mock())
        module._get_last_report = Mock(return_value=last_report)

        result1, last_report1 = module._calculate_distribution(blockstamp)

        result2, last_report2 = module._calculate_distribution(blockstamp)

        assert result1 is result2
        assert last_report1 is last_report2
        assert result1 is mock_distribution_result
        assert last_report1 is last_report

        assert MockDistribution.call_count == 1
        MockDistribution.assert_called_once_with(module.w3, module._get_web3_converter.return_value, state)
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
