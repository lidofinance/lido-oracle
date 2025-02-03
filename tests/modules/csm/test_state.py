from pathlib import Path
from unittest.mock import Mock

import pytest

from src.modules.csm.state import DutyAccumulator, State, calculate_frames
from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence


@pytest.fixture()
def state_file_path(tmp_path: Path) -> Path:
    return (tmp_path / "mock").with_suffix(State.EXTENSION)


@pytest.fixture(autouse=True)
def mock_state_file(state_file_path: Path):
    State.file = Mock(return_value=state_file_path)


def test_attestation_aggregate_perf():
    aggr = DutyAccumulator(included=333, assigned=777)
    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


def test_state_avg_perf():
    state = State()

    frame = (0, 999)

    with pytest.raises(ValueError):
        state.get_att_network_aggr(frame)

    state = State()
    state.init_or_migrate(*frame, 1000, 1)
    state.att_data = {
        frame: {
            ValidatorIndex(0): DutyAccumulator(included=0, assigned=0),
            ValidatorIndex(1): DutyAccumulator(included=0, assigned=0),
        }
    }

    assert state.get_att_network_aggr(frame).perf == 0

    state.att_data = {
        frame: {
            ValidatorIndex(0): DutyAccumulator(included=333, assigned=777),
            ValidatorIndex(1): DutyAccumulator(included=167, assigned=223),
        }
    }

    assert state.get_att_network_aggr(frame).perf == 0.5


def test_state_attestations():
    state = State(
        {
            (0, 999): {
                ValidatorIndex(0): DutyAccumulator(included=333, assigned=777),
                ValidatorIndex(1): DutyAccumulator(included=167, assigned=223),
            }
        }
    )

    network_aggr = state.get_att_network_aggr((0, 999))

    assert network_aggr.assigned == 1000
    assert network_aggr.included == 500


def test_state_load():
    orig = State(
        {
            (0, 999): {
                ValidatorIndex(0): DutyAccumulator(included=333, assigned=777),
                ValidatorIndex(1): DutyAccumulator(included=167, assigned=223),
            }
        }
    )

    orig.commit()
    copy = State.load()
    assert copy.att_data == orig.att_data


def test_state_clear():
    state = State(
        {
            (0, 999): {
                ValidatorIndex(0): DutyAccumulator(included=333, assigned=777),
                ValidatorIndex(1): DutyAccumulator(included=167, assigned=223),
            }
        }
    )

    state._epochs_to_process = (EpochNumber(1), EpochNumber(33))
    state._processed_epochs = {EpochNumber(42), EpochNumber(17)}

    state.clear()
    assert state.is_empty
    assert not state.att_data


def test_state_add_processed_epoch():
    state = State()
    state.add_processed_epoch(EpochNumber(42))
    state.add_processed_epoch(EpochNumber(17))
    assert state._processed_epochs == {EpochNumber(42), EpochNumber(17)}


def test_state_inc():

    frame_0 = (0, 999)
    frame_1 = (1000, 1999)

    state = State(
        {
            frame_0: {
                ValidatorIndex(0): DutyAccumulator(included=333, assigned=777),
                ValidatorIndex(1): DutyAccumulator(included=167, assigned=223),
            },
            frame_1: {
                ValidatorIndex(0): DutyAccumulator(included=1, assigned=1),
                ValidatorIndex(1): DutyAccumulator(included=0, assigned=1),
            },
        }
    )

    state.increment_att_duty(999, ValidatorIndex(0), True)
    state.increment_att_duty(999, ValidatorIndex(0), False)
    state.increment_att_duty(999, ValidatorIndex(1), True)
    state.increment_att_duty(999, ValidatorIndex(1), True)
    state.increment_att_duty(999, ValidatorIndex(1), False)
    state.increment_att_duty(999, ValidatorIndex(2), True)

    state.increment_att_duty(1000, ValidatorIndex(2), False)

    assert tuple(state.att_data[frame_0].values()) == (
        DutyAccumulator(included=334, assigned=779),
        DutyAccumulator(included=169, assigned=226),
        DutyAccumulator(included=1, assigned=1),
    )

    assert tuple(state.att_data[frame_1].values()) == (
        DutyAccumulator(included=1, assigned=1),
        DutyAccumulator(included=0, assigned=1),
        DutyAccumulator(included=0, assigned=1),
    )


def test_state_file_is_path():
    assert isinstance(State.file(), Path)


class TestStateTransition:
    """Tests for State's transition for different l_epoch, r_epoch values"""

    @pytest.fixture(autouse=True)
    def no_commit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(State, "commit", Mock())

    def test_empty_to_new_frame(self):
        state = State()
        assert state.is_empty

        l_epoch = EpochNumber(1)
        r_epoch = EpochNumber(255)

        state.init_or_migrate(l_epoch, r_epoch, 255, 1)

        assert not state.is_empty
        assert state.unprocessed_epochs == set(sequence(l_epoch, r_epoch))

    @pytest.mark.parametrize(
        ("l_epoch_old", "r_epoch_old", "l_epoch_new", "r_epoch_new"),
        [
            pytest.param(1, 255, 256, 510, id="Migrate a..bA..B"),
            pytest.param(1, 255, 32, 510, id="Migrate a..A..b..B"),
            pytest.param(32, 510, 1, 255, id="Migrate: A..a..B..b"),
        ],
    )
    def test_new_frame_requires_discarding_state(self, l_epoch_old, r_epoch_old, l_epoch_new, r_epoch_new):
        state = State()
        state.clear = Mock(side_effect=state.clear)
        state.init_or_migrate(l_epoch_old, r_epoch_old, r_epoch_old - l_epoch_old + 1, 1)
        state.clear.assert_not_called()

        state.init_or_migrate(l_epoch_new, r_epoch_new, r_epoch_new - l_epoch_new + 1, 1)
        state.clear.assert_called_once()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))

    @pytest.mark.parametrize(
        ("l_epoch_old", "r_epoch_old", "l_epoch_new", "r_epoch_new", "epochs_per_frame"),
        [
            pytest.param(1, 255, 1, 510, 255, id="Migrate Aa..b..B"),
        ],
    )
    def test_new_frame_extends_old_state(self, l_epoch_old, r_epoch_old, l_epoch_new, r_epoch_new, epochs_per_frame):
        state = State()
        state.clear = Mock(side_effect=state.clear)

        state.init_or_migrate(l_epoch_old, r_epoch_old, epochs_per_frame, 1)
        state.clear.assert_not_called()

        state.init_or_migrate(l_epoch_new, r_epoch_new, epochs_per_frame, 1)
        state.clear.assert_not_called()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))
        assert len(state.att_data) == 2
        assert list(state.att_data.keys()) == [(l_epoch_old, r_epoch_old), (r_epoch_old + 1, r_epoch_new)]
        assert calculate_frames(state._epochs_to_process, epochs_per_frame) == [
            (l_epoch_old, r_epoch_old),
            (r_epoch_old + 1, r_epoch_new),
        ]

    @pytest.mark.parametrize(
        ("l_epoch_old", "r_epoch_old", "epochs_per_frame_old", "l_epoch_new", "r_epoch_new", "epochs_per_frame_new"),
        [
            pytest.param(32, 510, 479, 1, 510, 510, id="Migrate: A..a..b..B"),
        ],
    )
    def test_new_frame_extends_old_state_with_single_frame(
        self, l_epoch_old, r_epoch_old, epochs_per_frame_old, l_epoch_new, r_epoch_new, epochs_per_frame_new
    ):
        state = State()
        state.clear = Mock(side_effect=state.clear)

        state.init_or_migrate(l_epoch_old, r_epoch_old, epochs_per_frame_old, 1)
        state.clear.assert_not_called()

        state.init_or_migrate(l_epoch_new, r_epoch_new, epochs_per_frame_new, 1)
        state.clear.assert_not_called()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))
        assert len(state.att_data) == 1
        assert list(state.att_data.keys())[0] == (l_epoch_new, r_epoch_new)
        assert calculate_frames(state._epochs_to_process, epochs_per_frame_new) == [(l_epoch_new, r_epoch_new)]

    @pytest.mark.parametrize(
        ("old_version", "new_version"),
        [
            pytest.param(2, 3, id="Increase consensus version"),
            pytest.param(3, 2, id="Decrease consensus version"),
        ],
    )
    def test_consensus_version_change(self, old_version, new_version):
        state = State()
        state.clear = Mock(side_effect=state.clear)
        state._consensus_version = old_version

        l_epoch = r_epoch = EpochNumber(255)

        state.init_or_migrate(l_epoch, r_epoch, 1, old_version)
        state.clear.assert_not_called()

        state.init_or_migrate(l_epoch, r_epoch, 1, new_version)
        state.clear.assert_called_once()
