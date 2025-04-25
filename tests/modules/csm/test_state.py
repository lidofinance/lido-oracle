from pathlib import Path
from unittest.mock import Mock

import pytest

from src.types import EpochNumber, ValidatorIndex
from src.modules.csm.state import AttestationsAccumulator, State
from src.utils.range import sequence


@pytest.fixture()
def state_file_path(tmp_path: Path) -> Path:
    return (tmp_path / "mock").with_suffix(State.EXTENSION)


@pytest.fixture(autouse=True)
def mock_state_file(state_file_path: Path):
    State.file = Mock(return_value=state_file_path)


def test_attestation_aggregate_perf():
    aggr = AttestationsAccumulator(included=333, assigned=777)
    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


def test_state_avg_perf():
    state = State()

    assert state.get_network_aggr().perf == 0

    state = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=0, assigned=0),
            ValidatorIndex(1): AttestationsAccumulator(included=0, assigned=0),
        }
    )

    assert state.get_network_aggr().perf == 0

    state = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAccumulator(included=167, assigned=223),
        }
    )

    assert state.get_network_aggr().perf == 0.5


def test_state_frame():
    state = State()

    state.migrate(EpochNumber(100), EpochNumber(500), 1)
    assert state.frame == (100, 500)

    state.migrate(EpochNumber(300), EpochNumber(301), 1)
    assert state.frame == (300, 301)

    state.clear()

    with pytest.raises(ValueError, match="Epochs to process are not set"):
        state.frame


def test_state_attestations():
    state = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAccumulator(included=167, assigned=223),
        }
    )

    network_aggr = state.get_network_aggr()

    assert network_aggr.assigned == 1000
    assert network_aggr.included == 500


def test_state_load():
    orig = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAccumulator(included=167, assigned=223),
        }
    )

    orig.commit()
    copy = State.load()
    assert copy.data == orig.data


def test_state_clear():
    state = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAccumulator(included=167, assigned=223),
        }
    )

    state._epochs_to_process = (EpochNumber(1), EpochNumber(33))
    state._processed_epochs = {EpochNumber(42), EpochNumber(17)}

    state.clear()
    assert state.is_empty
    assert not state.data


def test_state_add_processed_epoch():
    state = State()
    state.add_processed_epoch(EpochNumber(42))
    state.add_processed_epoch(EpochNumber(17))
    assert state._processed_epochs == {EpochNumber(42), EpochNumber(17)}


def test_state_inc():
    state = State(
        {
            ValidatorIndex(0): AttestationsAccumulator(included=0, assigned=0),
            ValidatorIndex(1): AttestationsAccumulator(included=1, assigned=2),
        }
    )

    state.inc(ValidatorIndex(0), True)
    state.inc(ValidatorIndex(0), False)

    state.inc(ValidatorIndex(1), True)
    state.inc(ValidatorIndex(1), True)
    state.inc(ValidatorIndex(1), False)

    state.inc(ValidatorIndex(2), True)
    state.inc(ValidatorIndex(2), False)

    assert tuple(state.data.values()) == (
        AttestationsAccumulator(included=1, assigned=2),
        AttestationsAccumulator(included=3, assigned=5),
        AttestationsAccumulator(included=1, assigned=2),
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

        state.migrate(l_epoch, r_epoch, 1)

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
        state.migrate(l_epoch_old, r_epoch_old, 2)
        state.clear.assert_not_called()

        state.migrate(l_epoch_new, r_epoch_new, 2)
        state.clear.assert_called_once()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))

    @pytest.mark.parametrize(
        ("l_epoch_old", "r_epoch_old", "l_epoch_new", "r_epoch_new"),
        [
            pytest.param(1, 255, 1, 510, id="Migrate Aa..b..B"),
            pytest.param(32, 510, 1, 510, id="Migrate: A..a..b..B"),
        ],
    )
    def test_new_frame_extends_old_state(self, l_epoch_old, r_epoch_old, l_epoch_new, r_epoch_new):
        state = State()
        state.clear = Mock(side_effect=state.clear)

        state.migrate(l_epoch_old, r_epoch_old, 2)
        state.clear.assert_not_called()

        state.migrate(l_epoch_new, r_epoch_new, 2)
        state.clear.assert_not_called()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))

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

        state.migrate(l_epoch, r_epoch, old_version)
        state.clear.assert_not_called()

        state.migrate(l_epoch, r_epoch, new_version)
        state.clear.assert_called_once()
