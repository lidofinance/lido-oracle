import os
import pickle
from collections import defaultdict
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import variables
from src.modules.csm.state import AttestationsAccumulator, State, InvalidState
from src.types import ValidatorIndex
from src.utils.range import sequence


@pytest.fixture(autouse=True)
def remove_state_files():
    state_file = Path("/tmp/state.pkl")
    state_buf = Path("/tmp/state.buf")
    state_file.unlink(missing_ok=True)
    state_buf.unlink(missing_ok=True)
    yield
    state_file.unlink(missing_ok=True)
    state_buf.unlink(missing_ok=True)


def test_load_restores_state_from_file(monkeypatch):
    monkeypatch.setattr("src.modules.csm.state.State.file", lambda _=None: Path("/tmp/state.pkl"))
    state = State()
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
    }
    state.commit()
    loaded_state = State.load()
    assert loaded_state.data == state.data


def test_load_returns_new_instance_if_file_not_found(monkeypatch):
    monkeypatch.setattr("src.modules.csm.state.State.file", lambda: Path("/non/existent/path"))
    state = State.load()
    assert state.is_empty


def test_load_returns_new_instance_if_empty_object(monkeypatch, tmp_path):
    with open('/tmp/state.pkl', "wb") as f:
        pickle.dump(None, f)
    monkeypatch.setattr("src.modules.csm.state.State.file", lambda: Path("/tmp/state.pkl"))
    state = State.load()
    assert state.is_empty


def test_commit_saves_state_to_file(monkeypatch):
    state = State()
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
    }
    monkeypatch.setattr("src.modules.csm.state.State.file", lambda _: Path("/tmp/state.pkl"))
    monkeypatch.setattr("os.replace", Mock(side_effect=os.replace))
    state.commit()
    with open("/tmp/state.pkl", "rb") as f:
        loaded_state = pickle.load(f)
    assert loaded_state.data == state.data
    os.replace.assert_called_once_with(Path("/tmp/state.buf"), Path("/tmp/state.pkl"))


def test_file_returns_correct_path(monkeypatch):
    monkeypatch.setattr(variables, "CACHE_PATH", Path("/tmp"))
    assert State.file() == Path("/tmp/cache.pkl")


def test_buffer_returns_correct_path(monkeypatch):
    monkeypatch.setattr(variables, "CACHE_PATH", Path("/tmp"))
    state = State()
    assert state.buffer == Path("/tmp/cache.buf")


def test_is_empty_returns_true_for_empty_state():
    state = State()
    assert state.is_empty


def test_is_empty_returns_false_for_non_empty_state():
    state = State()
    state.data = {(0, 31): defaultdict(AttestationsAccumulator)}
    assert not state.is_empty


def test_unprocessed_epochs_raises_error_if_epochs_not_set():
    state = State()
    with pytest.raises(ValueError, match="Epochs to process are not set"):
        state.unprocessed_epochs


def test_unprocessed_epochs_returns_correct_set():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 63))
    assert state.unprocessed_epochs == set(sequence(64, 95))


def test_is_fulfilled_returns_true_if_no_unprocessed_epochs():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 95))
    assert state.is_fulfilled


def test_is_fulfilled_returns_false_if_unprocessed_epochs_exist():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 63))
    assert not state.is_fulfilled


def test_calculate_frames_handles_exact_frame_size():
    epochs = tuple(range(10))
    frames = State._calculate_frames(epochs, 5)
    assert frames == [(0, 4), (5, 9)]


def test_calculate_frames_raises_error_for_insufficient_epochs():
    epochs = tuple(range(8))
    with pytest.raises(ValueError, match="Insufficient epochs to form a frame"):
        State._calculate_frames(epochs, 5)


def test_clear_resets_state_to_empty():
    state = State()
    state.data = {(0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)})}
    state.clear()
    assert state.is_empty


def test_find_frame_returns_correct_frame():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    state.data = {(0, 31): defaultdict(AttestationsAccumulator)}
    assert state.find_frame(15) == (0, 31)


def test_find_frame_raises_error_for_out_of_range_epoch():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    state.data = {(0, 31): defaultdict(AttestationsAccumulator)}
    with pytest.raises(ValueError, match="Epoch 32 is out of frames range"):
        state.find_frame(32)


def test_increment_duty_adds_duty_correctly():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
    }
    state.increment_duty(duty_epoch, ValidatorIndex(1), True)
    assert state.data[frame][ValidatorIndex(1)].assigned == 11
    assert state.data[frame][ValidatorIndex(1)].included == 6


def test_increment_duty_creates_new_validator_entry():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: defaultdict(AttestationsAccumulator),
    }
    state.increment_duty(duty_epoch, ValidatorIndex(2), True)
    assert state.data[frame][ValidatorIndex(2)].assigned == 1
    assert state.data[frame][ValidatorIndex(2)].included == 1


def test_increment_duty_handles_non_included_duty():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
    }
    state.increment_duty(duty_epoch, ValidatorIndex(1), False)
    assert state.data[frame][ValidatorIndex(1)].assigned == 11
    assert state.data[frame][ValidatorIndex(1)].included == 5


def test_increment_duty_raises_error_for_out_of_range_epoch():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator),
    }
    with pytest.raises(ValueError, match="is out of frames range"):
        state.increment_duty(32, ValidatorIndex(1), True)


def test_add_processed_epoch_adds_epoch_to_processed_set():
    state = State()
    state.add_processed_epoch(5)
    assert 5 in state._processed_epochs


def test_add_processed_epoch_does_not_duplicate_epochs():
    state = State()
    state.add_processed_epoch(5)
    state.add_processed_epoch(5)
    assert len(state._processed_epochs) == 1


def test_init_or_migrate_discards_data_on_version_change():
    state = State()
    state._consensus_version = 1
    state.clear = Mock()
    state.commit = Mock()
    state.init_or_migrate(0, 63, 32, 2)
    state.clear.assert_called_once()
    state.commit.assert_called_once()


def test_init_or_migrate_no_migration_needed():
    state = State()
    state._consensus_version = 1
    state._epochs_to_process = tuple(sequence(0, 63))
    state._epochs_per_frame = 32
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator),
        (32, 63): defaultdict(AttestationsAccumulator),
    }
    state.commit = Mock()
    state.init_or_migrate(0, 63, 32, 1)
    state.commit.assert_not_called()


def test_init_or_migrate_migrates_data():
    state = State()
    state._consensus_version = 1
    state._epochs_to_process = tuple(sequence(0, 63))
    state._epochs_per_frame = 32
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
        (32, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(20, 15)}),
    }
    state.commit = Mock()
    state.init_or_migrate(0, 63, 64, 1)
    assert state.data == {
        (0, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(30, 20)}),
    }
    state.commit.assert_called_once()


def test_init_or_migrate_invalidates_unmigrated_frames():
    state = State()
    state._consensus_version = 1
    state._epochs_to_process = tuple(sequence(0, 63))
    state._epochs_per_frame = 64
    state.data = {
        (0, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(30, 20)}),
    }
    state.commit = Mock()
    state.init_or_migrate(0, 31, 32, 1)
    assert state.data == {
        (0, 31): defaultdict(AttestationsAccumulator),
    }
    assert state._processed_epochs == set()
    state.commit.assert_called_once()


def test_init_or_migrate_discards_unmigrated_frame():
    state = State()
    state._consensus_version = 1
    state._epochs_to_process = tuple(sequence(0, 95))
    state._epochs_per_frame = 32
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
        (32, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(20, 15)}),
        (64, 95): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(30, 25)}),
    }
    state._processed_epochs = set(sequence(0, 95))
    state.commit = Mock()
    state.init_or_migrate(0, 63, 32, 1)
    assert state.data == {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
        (32, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(20, 15)}),
    }
    assert state._processed_epochs == set(sequence(0, 63))
    state.commit.assert_called_once()


def test_migrate_frames_data_creates_new_data_correctly():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 63))
    state._epochs_per_frame = 32
    new_frames = [(0, 63)]
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
        (32, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(20, 15)}),
    }
    state._migrate_frames_data(new_frames)
    assert state.data == {
        (0, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(30, 20)})
    }


def test_migrate_frames_data_handles_no_migration():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    new_frames = [(0, 31)]
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
    }
    state._migrate_frames_data(new_frames)
    assert state.data == {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)})
    }


def test_migrate_frames_data_handles_partial_migration():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 63))
    state._epochs_per_frame = 32
    new_frames = [(0, 31), (32, 95)]
    state.data = {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
        (32, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(20, 15)}),
    }
    state._migrate_frames_data(new_frames)
    assert state.data == {
        (0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 5)}),
        (32, 95): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(20, 15)}),
    }


def test_migrate_frames_data_handles_no_data():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 31))
    state._epochs_per_frame = 32
    current_frames = [(0, 31)]
    new_frames = [(0, 31)]
    state.data = {frame: defaultdict(AttestationsAccumulator) for frame in current_frames}
    state._migrate_frames_data(new_frames)
    assert state.data == {(0, 31): defaultdict(AttestationsAccumulator)}


def test_migrate_frames_data_handles_wider_old_frame():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 63))
    state._epochs_per_frame = 64
    new_frames = [(0, 31), (32, 63)]
    state.data = {
        (0, 63): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(30, 20)}),
    }
    state._migrate_frames_data(new_frames)
    assert state.data == {
        (0, 31): defaultdict(AttestationsAccumulator),
        (32, 63): defaultdict(AttestationsAccumulator),
    }


def test_validate_raises_error_if_state_not_fulfilled():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 94))
    with pytest.raises(InvalidState, match="State is not fulfilled"):
        state.validate(0, 95)


def test_validate_raises_error_if_processed_epoch_out_of_range():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 95))
    state._processed_epochs.add(96)
    with pytest.raises(InvalidState, match="Processed epoch 96 is out of range"):
        state.validate(0, 95)


def test_validate_raises_error_if_epoch_missing_in_processed_epochs():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 94))
    state._processed_epochs = set(sequence(0, 94))
    with pytest.raises(InvalidState, match="Epoch 95 missing in processed epochs"):
        state.validate(0, 95)


def test_validate_passes_for_fulfilled_state():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 95))
    state.validate(0, 95)


def test_attestation_aggregate_perf():
    aggr = AttestationsAccumulator(included=333, assigned=777)
    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


def test_get_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (0, 31): defaultdict(
            AttestationsAccumulator,
            {ValidatorIndex(1): AttestationsAccumulator(10, 5), ValidatorIndex(2): AttestationsAccumulator(20, 15)},
        )
    }
    aggr = state.get_network_aggr((0, 31))
    assert aggr.assigned == 30
    assert aggr.included == 20


def test_get_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {(0, 31): defaultdict(AttestationsAccumulator, {ValidatorIndex(1): AttestationsAccumulator(10, 15)})}
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_network_aggr((0, 31))


def test_get_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_network_aggr((0, 31))


def test_get_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(0, 31): defaultdict(AttestationsAccumulator)}
    aggr = state.get_network_aggr((0, 31))
    assert aggr.assigned == 0
    assert aggr.included == 0
