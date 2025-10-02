import os
import pickle
from collections import defaultdict
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import variables
from src.constants import CSM_STATE_VERSION
from src.modules.csm.state import DutyAccumulator, InvalidState, NetworkDuties, State
from src.types import ValidatorIndex
from src.utils.range import sequence


@pytest.fixture()
def state_file_path(tmp_path: Path) -> Path:
    return (tmp_path / "mock").with_suffix(State.EXTENSION)


@pytest.fixture(autouse=True)
def mock_state_file(state_file_path: Path):
    State.file = Mock(return_value=state_file_path)


class TestCachePathConfigurable:
    @pytest.fixture()
    def mock_state_file(self):
        # NOTE: Overrides file-level mock_state_file to check the mechanic.
        pass

    @pytest.fixture()
    def cache_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(variables, "CACHE_PATH", tmp_path)
        return tmp_path

    @pytest.mark.unit
    def test_file_returns_correct_path(self, cache_path: Path):
        assert State.file() == cache_path / "cache.pkl"

    @pytest.mark.unit
    def test_buffer_returns_correct_path(self, cache_path: Path):
        state = State()
        assert state.buffer == cache_path / "cache.buf"


@pytest.mark.unit
def test_load_restores_state_from_file():
    state = State()
    state.data = {
        (0, 31): defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
    }
    state.commit()
    loaded_state = State.load()
    assert loaded_state.data == state.data


@pytest.mark.unit
def test_load_returns_new_instance_if_file_not_found(state_file_path: Path):
    assert not state_file_path.exists()
    state = State.load()
    assert state.is_empty


@pytest.mark.unit
def test_load_returns_new_instance_if_empty_object(state_file_path: Path):
    with open(state_file_path, "wb") as f:
        pickle.dump(None, f)
    state = State.load()
    assert state.is_empty


@pytest.mark.unit
def test_commit_saves_state_to_file(state_file_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = State()
    state.data = {
        (0, 31): defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
    }
    with monkeypatch.context() as mp:
        os_replace_mock = Mock(side_effect=os.replace)
        mp.setattr("os.replace", os_replace_mock)
        state.commit()
        with open(state_file_path, "rb") as f:
            loaded_state = pickle.load(f)
        assert loaded_state.data == state.data
        os_replace_mock.assert_called_once_with(state_file_path.with_suffix(".buf"), state_file_path)


@pytest.mark.unit
def test_is_empty_returns_true_for_empty_state():
    state = State()
    assert state.is_empty


@pytest.mark.unit
def test_is_empty_returns_false_for_non_empty_state():
    state = State()
    state.data = {(0, 31): NetworkDuties()}
    assert not state.is_empty


@pytest.mark.unit
def test_unprocessed_epochs_raises_error_if_epochs_not_set():
    state = State()
    with pytest.raises(ValueError, match="Epochs to process are not set"):
        state.unprocessed_epochs


@pytest.mark.unit
def test_unprocessed_epochs_returns_correct_set():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 63))
    assert state.unprocessed_epochs == set(sequence(64, 95))


@pytest.mark.unit
def test_is_fulfilled_returns_true_if_no_unprocessed_epochs():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 95))
    assert state.is_fulfilled


@pytest.mark.unit
def test_is_fulfilled_returns_false_if_unprocessed_epochs_exist():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 63))
    assert not state.is_fulfilled


@pytest.mark.unit
def test_calculate_frames_handles_exact_frame_size():
    epochs = tuple(range(10))
    frames = State._calculate_frames(epochs, 5)
    assert frames == [(0, 4), (5, 9)]


@pytest.mark.unit
def test_calculate_frames_raises_error_for_insufficient_epochs():
    epochs = tuple(range(8))
    with pytest.raises(ValueError, match="Insufficient epochs to form a frame"):
        State._calculate_frames(epochs, 5)


@pytest.mark.unit
def test_clear_resets_state_to_empty():
    state = State()
    state.data = {(0, 31): defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})}
    state.clear()
    assert state.is_empty


@pytest.mark.unit
def test_find_frame_returns_correct_frame():
    state = State()
    state.data = {(0, 31): {}}
    assert state.find_frame(15) == (0, 31)


@pytest.mark.unit
def test_find_frame_raises_error_for_out_of_range_epoch():
    state = State()
    state.data = {(0, 31): {}}
    with pytest.raises(ValueError, match="Epoch 32 is out of frames range"):
        state.find_frame(32)


@pytest.mark.unit
def test_increment_att_duty_adds_duty_correctly():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_att_duty(duty_epoch, ValidatorIndex(1), True)
    assert state.data[frame].attestations[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].attestations[ValidatorIndex(1)].included == 6


@pytest.mark.unit
def test_increment_prop_duty_adds_duty_correctly():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_prop_duty(duty_epoch, ValidatorIndex(1), True)
    assert state.data[frame].proposals[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].proposals[ValidatorIndex(1)].included == 6


@pytest.mark.unit
def test_increment_sync_duty_adds_duty_correctly():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_sync_duty(duty_epoch, ValidatorIndex(1), True)
    assert state.data[frame].syncs[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].syncs[ValidatorIndex(1)].included == 6


@pytest.mark.unit
def test_increment_att_duty_creates_new_validator_entry():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(),
    }
    state.save_att_duty(duty_epoch, ValidatorIndex(2), True)
    assert state.data[frame].attestations[ValidatorIndex(2)].assigned == 1
    assert state.data[frame].attestations[ValidatorIndex(2)].included == 1


@pytest.mark.unit
def test_increment_prop_duty_creates_new_validator_entry():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(),
    }
    state.save_prop_duty(duty_epoch, ValidatorIndex(2), True)
    assert state.data[frame].proposals[ValidatorIndex(2)].assigned == 1
    assert state.data[frame].proposals[ValidatorIndex(2)].included == 1


@pytest.mark.unit
def test_increment_sync_duty_creates_new_validator_entry():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(),
    }
    state.save_sync_duty(duty_epoch, ValidatorIndex(2), True)
    assert state.data[frame].syncs[ValidatorIndex(2)].assigned == 1
    assert state.data[frame].syncs[ValidatorIndex(2)].included == 1


@pytest.mark.unit
def test_increment_att_duty_handles_non_included_duty():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_att_duty(duty_epoch, ValidatorIndex(1), False)
    assert state.data[frame].attestations[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].attestations[ValidatorIndex(1)].included == 5


@pytest.mark.unit
def test_increment_prop_duty_handles_non_included_duty():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_prop_duty(duty_epoch, ValidatorIndex(1), False)
    assert state.data[frame].proposals[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].proposals[ValidatorIndex(1)].included == 5


@pytest.mark.unit
def test_increment_sync_duty_handles_non_included_duty():
    state = State()
    frame = (0, 31)
    duty_epoch, _ = frame
    state.data = {
        frame: NetworkDuties(syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)})),
    }
    state.save_sync_duty(duty_epoch, ValidatorIndex(1), False)
    assert state.data[frame].syncs[ValidatorIndex(1)].assigned == 11
    assert state.data[frame].syncs[ValidatorIndex(1)].included == 5


@pytest.mark.unit
def test_increment_att_duty_raises_error_for_out_of_range_epoch():
    state = State()
    state.att_data = {
        (0, 31): defaultdict(DutyAccumulator),
    }
    with pytest.raises(ValueError, match="is out of frames range"):
        state.save_att_duty(32, ValidatorIndex(1), True)


@pytest.mark.unit
def test_increment_prop_duty_raises_error_for_out_of_range_epoch():
    state = State()
    state.att_data = {
        (0, 31): defaultdict(DutyAccumulator),
    }
    with pytest.raises(ValueError, match="is out of frames range"):
        state.save_prop_duty(32, ValidatorIndex(1), True)


@pytest.mark.unit
def test_increment_sync_duty_raises_error_for_out_of_range_epoch():
    state = State()
    state.att_data = {
        (0, 31): defaultdict(DutyAccumulator),
    }
    with pytest.raises(ValueError, match="is out of frames range"):
        state.save_sync_duty(32, ValidatorIndex(1), True)


@pytest.mark.unit
def test_add_processed_epoch_adds_epoch_to_processed_set():
    state = State()
    state.add_processed_epoch(5)
    assert 5 in state._processed_epochs


@pytest.mark.unit
def test_add_processed_epoch_does_not_duplicate_epochs():
    state = State()
    state.add_processed_epoch(5)
    state.add_processed_epoch(5)
    assert len(state._processed_epochs) == 1


@pytest.mark.unit
def test_migrate_discards_data_on_version_change():
    state = State()
    state._version = CSM_STATE_VERSION + 1
    state.clear = Mock()
    state.commit = Mock()
    state.migrate(0, 63, 32)

    state.clear.assert_called_once()
    state.commit.assert_called_once()
    assert state.frames == [(0, 31), (32, 63)]
    assert state._epochs_to_process == tuple(sequence(0, 63))
    assert state.version == CSM_STATE_VERSION


@pytest.mark.unit
def test_migrate_no_migration_needed():
    state = State()
    state.data = {
        (0, 31): defaultdict(DutyAccumulator),
        (32, 63): defaultdict(DutyAccumulator),
    }
    state._epochs_to_process = tuple(sequence(0, 63))
    state.commit = Mock()
    state.migrate(0, 63, 32)

    assert state.frames == [(0, 31), (32, 63)]
    assert state._epochs_to_process == tuple(sequence(0, 63))
    assert state.version == CSM_STATE_VERSION
    state.commit.assert_not_called()


@pytest.mark.unit
def test_migrate_migrates_data():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
        (32, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(20, 15)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(20, 15)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(20, 15)}),
        ),
    }
    state.commit = Mock()
    state.migrate(0, 63, 64)

    assert state.data == {
        (0, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(30, 20)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(30, 20)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(30, 20)}),
        ),
    }
    assert state.frames == [(0, 63)]
    assert state._epochs_to_process == tuple(sequence(0, 63))
    assert state.version == CSM_STATE_VERSION
    state.commit.assert_called_once()


@pytest.mark.unit
def test_migrate_invalidates_unmigrated_frames():
    state = State()
    state._consensus_version = 1
    state.data = {
        (0, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(30, 20)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(30, 20)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(30, 20)}),
        ),
    }
    state.commit = Mock()
    state.migrate(0, 31, 32)

    assert state.data == {
        (0, 31): NetworkDuties(),
    }
    assert state._processed_epochs == set()
    assert state.frames == [(0, 31)]
    assert state._epochs_to_process == tuple(sequence(0, 31))
    assert state._consensus_version == 1
    state.commit.assert_called_once()


@pytest.mark.unit
def test_migrate_discards_unmigrated_frame():
    state = State()
    state._consensus_version = 1
    state.data = {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
        (32, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(20, 15)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(20, 15)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(20, 15)}),
        ),
        (64, 95): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(30, 25)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(30, 25)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(30, 25)}),
        ),
    }
    state._processed_epochs = set(sequence(0, 95))
    state.commit = Mock()
    state.migrate(0, 63, 32)

    assert state.data == {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
        (32, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(20, 15)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(20, 15)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(20, 15)}),
        ),
    }
    assert state._processed_epochs == set(sequence(0, 63))
    assert state.frames == [(0, 31), (32, 63)]
    assert state._epochs_to_process == tuple(sequence(0, 63))
    assert state._consensus_version == 1
    state.commit.assert_called_once()


@pytest.mark.unit
def test_migrate_frames_data_creates_new_data_correctly():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
        (32, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(20, 15)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(20, 15)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(20, 15)}),
        ),
    }
    state._processed_epochs = set(sequence(0, 20))

    new_frames = [(0, 63)]
    state._migrate_frames_data(new_frames)

    assert state.data == {
        (0, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(30, 20)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(30, 20)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(30, 20)}),
        ),
    }
    assert state._processed_epochs == set(sequence(0, 20))


@pytest.mark.unit
def test_migrate_frames_data_handles_no_migration():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
    }
    state._processed_epochs = set(sequence(0, 20))

    new_frames = [(0, 31)]
    state._migrate_frames_data(new_frames)

    assert state.data == {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
    }
    assert state._processed_epochs == set(sequence(0, 20))


@pytest.mark.unit
def test_migrate_frames_data_handles_partial_migration():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
        (32, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(20, 15)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(20, 15)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(20, 15)}),
        ),
    }
    state._processed_epochs = set(sequence(0, 20))

    new_frames = [(0, 31), (32, 95)]
    state._migrate_frames_data(new_frames)

    assert state.data == {
        (0, 31): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 5)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(10, 5)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(10, 5)}),
        ),
        (32, 95): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(20, 15)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(20, 15)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(20, 15)}),
        ),
    }
    assert state._processed_epochs == set(sequence(0, 20))


@pytest.mark.unit
def test_migrate_frames_data_handles_no_data():
    state = State()
    state.data = {frame: NetworkDuties() for frame in state.frames}

    new_frames = [(0, 31)]
    state._migrate_frames_data(new_frames)

    assert state.data == {(0, 31): NetworkDuties()}


@pytest.mark.unit
def test_migrate_frames_data_handles_wider_old_frame():
    state = State()
    state.data = {
        (0, 63): NetworkDuties(
            attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(30, 20)}),
            proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(30, 20)}),
            syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(30, 20)}),
        ),
    }
    state._processed_epochs = set(sequence(0, 20))

    new_frames = [(0, 31), (32, 63)]
    state._migrate_frames_data(new_frames)

    assert state.data == {
        (0, 31): NetworkDuties(),
        (32, 63): NetworkDuties(),
    }
    assert state._processed_epochs == set()


@pytest.mark.unit
def test_validate_raises_error_if_state_not_fulfilled():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 94))
    with pytest.raises(InvalidState, match="State is not fulfilled"):
        state.validate(0, 95)


@pytest.mark.unit
def test_validate_raises_error_if_processed_epoch_out_of_range():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 95))
    state._processed_epochs.add(96)
    with pytest.raises(InvalidState, match="Processed epoch 96 is out of range"):
        state.validate(0, 95)


@pytest.mark.unit
def test_validate_raises_error_if_epoch_missing_in_processed_epochs():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 94))
    state._processed_epochs = set(sequence(0, 94))
    with pytest.raises(InvalidState, match="Epoch 95 missing in processed epochs"):
        state.validate(0, 95)


@pytest.mark.unit
def test_validate_passes_for_fulfilled_state():
    state = State()
    state._epochs_to_process = tuple(sequence(0, 95))
    state._processed_epochs = set(sequence(0, 95))
    state.validate(0, 95)


@pytest.mark.unit
def test_attestation_aggregate_perf():
    aggr = DutyAccumulator(included=333, assigned=777)
    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


@pytest.mark.unit
def test_get_validator_duties():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
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
    duties = state.get_validator_duties((0, 31), ValidatorIndex(1))
    assert duties.attestation.assigned == 10
    assert duties.attestation.included == 5
    assert duties.proposal.assigned == 7
    assert duties.proposal.included == 1
    assert duties.sync.assigned == 3
    assert duties.sync.included == 2


@pytest.mark.unit
def test_get_att_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            attestations=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }
    aggr = state.get_att_network_aggr((0, 31))
    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_sync_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            syncs=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }
    aggr = state.get_sync_network_aggr((0, 31))
    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_prop_network_aggr_computes_correctly():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(
            proposals=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }
    aggr = state.get_prop_network_aggr((0, 31))
    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_att_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 15)}))
    }
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_att_network_aggr((0, 31))


@pytest.mark.unit
def test_get_prop_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(proposals=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 15)}))
    }
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_prop_network_aggr((0, 31))


@pytest.mark.unit
def test_get_sync_network_aggr_raises_error_for_invalid_accumulator():
    state = State()
    state.data = {
        (0, 31): NetworkDuties(syncs=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(10, 15)}))
    }
    with pytest.raises(ValueError, match="Invalid accumulator"):
        state.get_sync_network_aggr((0, 31))


@pytest.mark.unit
def test_get_att_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_att_network_aggr((0, 31))


@pytest.mark.unit
def test_get_prop_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_prop_network_aggr((0, 31))


@pytest.mark.unit
def test_get_sync_network_aggr_raises_error_for_missing_frame_data():
    state = State()
    with pytest.raises(ValueError, match="No data for frame"):
        state.get_sync_network_aggr((0, 31))


@pytest.mark.unit
def test_get_att_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(0, 31): NetworkDuties()}
    aggr = state.get_att_network_aggr((0, 31))
    assert aggr.assigned == 0
    assert aggr.included == 0


@pytest.mark.unit
def test_get_prop_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(0, 31): NetworkDuties()}
    aggr = state.get_prop_network_aggr((0, 31))
    assert aggr.assigned == 0
    assert aggr.included == 0


@pytest.mark.unit
def test_get_sync_network_aggr_handles_empty_frame_data():
    state = State()
    state.data = {(0, 31): NetworkDuties()}
    aggr = state.get_sync_network_aggr((0, 31))
    assert aggr.assigned == 0
    assert aggr.included == 0
