from collections import defaultdict
from unittest.mock import Mock

import pytest

from modules.oracles.staking_modules.common.state import DutyAccumulator, Frame, InvalidState, NetworkDuties, State
from type_aliases import EpochNumber, ValidatorIndex
from utils.range import sequence


@pytest.mark.unit
def test_is_empty_returns_true_for_empty_state():
    state = State()
    assert state.is_empty


@pytest.mark.unit
def test_is_empty_returns_false_for_non_empty_state():
    state = State()
    state.data = {(EpochNumber(0), EpochNumber(31)): NetworkDuties()}
    assert not state.is_empty


@pytest.mark.unit
def test_unprocessed_epochs_raises_error_if_epochs_not_set():
    state = State()
    with pytest.raises(ValueError, match="Epochs to process are not set"):
        _ = state.unprocessed_epochs


@pytest.mark.unit
def test_unprocessed_epochs_returns_correct_set():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 63))
    assert state.unprocessed_epochs == set(EpochNumber(e) for e in sequence(64, 95))


@pytest.mark.unit
def test_is_fulfilled_returns_true_if_no_unprocessed_epochs():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 95))
    assert state.is_fulfilled


@pytest.mark.unit
def test_is_fulfilled_returns_false_if_unprocessed_epochs_exist():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 63))
    assert not state.is_fulfilled


@pytest.mark.unit
def test_calculate_frames_handles_exact_frame_size():
    epochs = tuple(EpochNumber(e) for e in range(10))
    frames = State._calculate_frames(epochs, 5)
    assert frames == [(EpochNumber(0), EpochNumber(4)), (EpochNumber(5), EpochNumber(9))]


@pytest.mark.unit
def test_calculate_frames_raises_error_for_insufficient_epochs():
    epochs = tuple(EpochNumber(e) for e in range(8))
    with pytest.raises(ValueError, match="Insufficient epochs to form a frame"):
        State._calculate_frames(epochs, 5)


@pytest.mark.unit
@pytest.mark.parametrize(
    "frames, expected",
    [
        pytest.param(((10, 41),), (10, 41), id="single-frame"),
        pytest.param(((0, 31), (32, 63)), (0, 63), id="sorted-frames"),
        pytest.param(((32, 63), (0, 31)), (0, 63), id="unsorted-two-frames"),
        pytest.param(((64, 95), (32, 63), (0, 31)), (0, 95), id="reverse-three-frames"),
        pytest.param(((32, 63), (64, 95), (0, 31)), (0, 95), id="mixed-three-frames"),
    ],
)
def test_range_returns_expected_bounds(frames, expected):
    state = State()
    state.data = {frame: NetworkDuties() for frame in frames}
    assert state.frame_range == expected


@pytest.mark.unit
def test_range_raises_error_when_no_frames():
    state = State()
    with pytest.raises(InvalidState, match="Frames are not set"):
        _ = state.frame_range


@pytest.mark.unit
def test_clear_resets_state_to_empty():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})
        ),
    }
    state.clear()
    assert state.is_empty


@pytest.mark.unit
def test_find_frame_returns_correct_frame():
    state = State()
    state.data = {(EpochNumber(0), EpochNumber(31)): NetworkDuties()}
    assert state.find_frame(EpochNumber(15)) == (EpochNumber(0), EpochNumber(31))


@pytest.mark.unit
def test_find_frame_raises_error_for_out_of_range_epoch():
    state = State()
    state.data = {(EpochNumber(0), EpochNumber(31)): NetworkDuties()}
    with pytest.raises(ValueError, match="Epoch 32 is out of frames range"):
        state.find_frame(EpochNumber(32))


@pytest.mark.unit
def test_increment_att_duty_adds_duty_correctly():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_att_duty(duty_epoch, ValidatorIndex(1), DutyAccumulator(assigned=1, included=1))
    assert state.data[frame].attestations[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].attestations[ValidatorIndex(1)].included == 6


@pytest.mark.unit
def test_increment_prop_duty_adds_duty_correctly():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_prop_duty(duty_epoch, ValidatorIndex(1), DutyAccumulator(assigned=1, included=1))
    assert state.data[frame].proposals[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].proposals[ValidatorIndex(1)].included == 6


@pytest.mark.unit
def test_increment_sync_duty_adds_duty_correctly():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_sync_duty(duty_epoch, ValidatorIndex(1), DutyAccumulator(assigned=1, included=1))
    assert state.data[frame].syncs[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].syncs[ValidatorIndex(1)].included == 6


@pytest.mark.unit
def test_increment_att_duty_creates_new_validator_entry():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(),
    }
    state.save_att_duty(duty_epoch, ValidatorIndex(2), DutyAccumulator(assigned=1, included=1))
    assert state.data[frame].attestations[ValidatorIndex(2)].assigned == 1
    assert state.data[frame].attestations[ValidatorIndex(2)].included == 1


@pytest.mark.unit
def test_increment_prop_duty_creates_new_validator_entry():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(),
    }
    state.save_prop_duty(duty_epoch, ValidatorIndex(2), DutyAccumulator(assigned=1, included=1))
    assert state.data[frame].proposals[ValidatorIndex(2)].assigned == 1
    assert state.data[frame].proposals[ValidatorIndex(2)].included == 1


@pytest.mark.unit
def test_increment_sync_duty_creates_new_validator_entry():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(),
    }
    state.save_sync_duty(duty_epoch, ValidatorIndex(2), DutyAccumulator(assigned=1, included=1))
    assert state.data[frame].syncs[ValidatorIndex(2)].assigned == 1
    assert state.data[frame].syncs[ValidatorIndex(2)].included == 1


@pytest.mark.unit
def test_increment_att_duty_handles_non_included_duty():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_att_duty(duty_epoch, ValidatorIndex(1), DutyAccumulator(assigned=1, included=0))
    assert state.data[frame].attestations[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].attestations[ValidatorIndex(1)].included == 5


@pytest.mark.unit
def test_increment_prop_duty_handles_non_included_duty():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_prop_duty(duty_epoch, ValidatorIndex(1), DutyAccumulator(assigned=1, included=0))
    assert state.data[frame].proposals[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].proposals[ValidatorIndex(1)].included == 5


@pytest.mark.unit
def test_increment_sync_duty_handles_non_included_duty():
    state = State()
    frame: Frame = (EpochNumber(0), EpochNumber(31))
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_sync_duty(duty_epoch, ValidatorIndex(1), DutyAccumulator(assigned=1, included=0))
    assert state.data[frame].syncs[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].syncs[ValidatorIndex(1)].included == 5


@pytest.mark.unit
def test_increment_att_duty_raises_error_for_out_of_range_epoch():
    state = State()
    with pytest.raises(ValueError, match="is out of frames range"):
        state.save_att_duty(EpochNumber(32), ValidatorIndex(1), DutyAccumulator(assigned=1, included=1))


@pytest.mark.unit
def test_increment_prop_duty_raises_error_for_out_of_range_epoch():
    state = State()
    with pytest.raises(ValueError, match="is out of frames range"):
        state.save_prop_duty(EpochNumber(32), ValidatorIndex(1), DutyAccumulator(assigned=1, included=1))


@pytest.mark.unit
def test_increment_sync_duty_raises_error_for_out_of_range_epoch():
    state = State()
    with pytest.raises(ValueError, match="is out of frames range"):
        state.save_sync_duty(EpochNumber(32), ValidatorIndex(1), DutyAccumulator(assigned=1, included=1))


@pytest.mark.unit
def test_add_processed_epoch_adds_epoch_to_processed_set():
    state = State()
    state.add_processed_epoch(EpochNumber(5))
    assert EpochNumber(5) in state._processed_epochs


@pytest.mark.unit
def test_add_processed_epoch_does_not_duplicate_epochs():
    state = State()
    state.add_processed_epoch(EpochNumber(5))
    state.add_processed_epoch(EpochNumber(5))
    assert len(state._processed_epochs) == 1


@pytest.mark.unit
def test_init():
    state = State()
    state._calculate_frames = Mock(side_effect=state._calculate_frames)

    state.init(EpochNumber(0), EpochNumber(63), 64)

    assert state.data == {
        (EpochNumber(0), EpochNumber(63)): NetworkDuties(attestations={}, proposals={}, syncs={}),
    }
    assert state.frames == [(EpochNumber(0), EpochNumber(63))]
    assert state._epochs_to_process == tuple(EpochNumber(e) for e in sequence(0, 63))
    state._calculate_frames.assert_called_once_with(tuple(sequence(0, 63)), 64)


@pytest.mark.unit
def test_init_multiple_frames():
    state = State()
    state._calculate_frames = Mock(side_effect=state._calculate_frames)

    state.init(EpochNumber(0), EpochNumber(127), 64)

    assert state.data == {
        (EpochNumber(0), EpochNumber(63)): NetworkDuties(attestations={}, proposals={}, syncs={}),
        (EpochNumber(64), EpochNumber(127)): NetworkDuties(attestations={}, proposals={}, syncs={}),
    }
    assert state.frames == [(EpochNumber(0), EpochNumber(63)), (EpochNumber(64), EpochNumber(127))]
    state._calculate_frames.assert_called_once_with(tuple(sequence(0, 127)), 64)


@pytest.mark.unit
def test_reinit_after_clear():
    state = State()
    state.init(EpochNumber(0), EpochNumber(63), 64)
    state.clear()
    state.init(EpochNumber(0), EpochNumber(63), 64)
    assert state.data == {(EpochNumber(0), EpochNumber(63)): NetworkDuties(attestations={}, proposals={}, syncs={})}
    assert state.frames == [(EpochNumber(0), EpochNumber(63))]


@pytest.mark.unit
def test_clear_then_init_resets_find_frame_cache():
    state = State()
    state.init(EpochNumber(0), EpochNumber(63), 64)
    assert state.find_frame(EpochNumber(10)) == (EpochNumber(0), EpochNumber(63))

    state.clear()
    state.init(EpochNumber(0), EpochNumber(63), 32)

    assert state.find_frame(EpochNumber(10)) == (EpochNumber(0), EpochNumber(31))


@pytest.mark.unit
def test_init_raises_if_already_initialized():
    state = State()
    state.init(EpochNumber(0), EpochNumber(127), 64)
    with pytest.raises(InvalidState, match="initialized"):
        state.init(EpochNumber(0), EpochNumber(127), 64)


@pytest.mark.unit
def test_validate_raises_error_if_state_not_fulfilled():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 94))
    with pytest.raises(InvalidState, match="State is not fulfilled"):
        state.validate(EpochNumber(0), EpochNumber(95))


@pytest.mark.unit
def test_validate_raises_error_if_processed_epoch_out_of_range():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs.add(EpochNumber(96))
    with pytest.raises(InvalidState, match="Processed epoch 96 is out of range"):
        state.validate(EpochNumber(0), EpochNumber(95))


@pytest.mark.unit
def test_validate_raises_error_if_epoch_missing_in_processed_epochs():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 94))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 94))
    with pytest.raises(InvalidState, match="Epoch 95 missing in processed epochs"):
        state.validate(EpochNumber(0), EpochNumber(95))


@pytest.mark.unit
def test_validate_passes_for_fulfilled_state():
    state = State()
    state._epochs_to_process = tuple(EpochNumber(e) for e in sequence(0, 95))
    state._processed_epochs = set(EpochNumber(e) for e in sequence(0, 95))
    state.validate(EpochNumber(0), EpochNumber(95))


@pytest.mark.unit
def test_attestation_aggregate_perf():
    aggr = DutyAccumulator(included=333, assigned=777)
    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


@pytest.mark.unit
def test_get_validator_duties():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            attestations=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            ),
            proposals=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(7, 1), ValidatorIndex(2): DutyAccumulator(20, 15)},
            ),
            syncs=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(3, 2), ValidatorIndex(2): DutyAccumulator(20, 15)},
            ),
        )
    }
    duties = state.get_validator_duties((EpochNumber(0), EpochNumber(31)), ValidatorIndex(1))
    assert duties.attestation is not None
    assert duties.attestation.assigned == 10
    assert duties.attestation.included == 5
    assert duties.proposal is not None
    assert duties.proposal.assigned == 7
    assert duties.proposal.included == 1
    assert duties.sync is not None
    assert duties.sync.assigned == 3
    assert duties.sync.included == 2


@pytest.mark.unit
def test_get_att_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            attestations=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }
    aggr = state.get_att_network_aggr((EpochNumber(0), EpochNumber(31)))
    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_sync_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            syncs=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }
    aggr = state.get_sync_network_aggr((EpochNumber(0), EpochNumber(31)))
    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_prop_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            proposals=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }
    aggr = state.get_prop_network_aggr((EpochNumber(0), EpochNumber(31)))
    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_att_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 15)})
        )
    }
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_att_network_aggr((EpochNumber(0), EpochNumber(31)))


@pytest.mark.unit
def test_get_prop_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 15)})
        )
    }
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_prop_network_aggr((EpochNumber(0), EpochNumber(31)))


@pytest.mark.unit
def test_get_sync_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 15)})
        )
    }
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_sync_network_aggr((EpochNumber(0), EpochNumber(31)))


@pytest.mark.unit
def test_get_att_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_att_network_aggr((EpochNumber(0), EpochNumber(31)))


@pytest.mark.unit
def test_get_prop_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_prop_network_aggr((EpochNumber(0), EpochNumber(31)))


@pytest.mark.unit
def test_get_sync_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_sync_network_aggr((EpochNumber(0), EpochNumber(31)))


@pytest.mark.unit
def test_get_att_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(EpochNumber(0), EpochNumber(31)): NetworkDuties()}
    aggr = state.get_att_network_aggr((EpochNumber(0), EpochNumber(31)))
    assert aggr.assigned == 0
    assert aggr.included == 0


@pytest.mark.unit
def test_get_prop_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(EpochNumber(0), EpochNumber(31)): NetworkDuties()}
    aggr = state.get_prop_network_aggr((EpochNumber(0), EpochNumber(31)))
    assert aggr.assigned == 0
    assert aggr.included == 0


@pytest.mark.unit
def test_get_sync_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(EpochNumber(0), EpochNumber(31)): NetworkDuties()}
    aggr = state.get_sync_network_aggr((EpochNumber(0), EpochNumber(31)))
    assert aggr.assigned == 0
    assert aggr.included == 0
