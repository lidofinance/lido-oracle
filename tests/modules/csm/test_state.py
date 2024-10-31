from pathlib import Path
from unittest.mock import Mock

import pytest

from src.modules.csm.state import State
from src.modules.csm.duties.attestation import AttestationSequence, AttestationStatus, calc_performance
from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence


@pytest.fixture()
def state_file_path(tmp_path: Path) -> Path:
    return (tmp_path / "mock").with_suffix(State.EXTENSION)


@pytest.fixture(autouse=True)
def mock_state_file(state_file_path: Path):
    State.file = Mock(return_value=state_file_path)


def test_calc_performance():
    assert calc_performance(333, 444) == pytest.approx(0.4285, abs=1e-4)


def test_state_frame():
    state = State()

    state.migrate(EpochNumber(100), EpochNumber(500))
    assert state.calc_frames(401) == [(100, 500)]

    state.migrate(EpochNumber(300), EpochNumber(301))
    assert state.calc_frames(2) == [(300, 301)]

    state.clear()

    assert state.calc_frames(1) == []


def test_state_network_perf():
    state = State()
    state.migrate(EpochNumber(0), EpochNumber(1))
    state.data = [
        AttestationSequence(2),
        AttestationSequence(2),
    ]

    state.set_duty_status(0, 0, True)
    state.set_duty_status(0, 1, False)
    state.set_duty_status(1, 0, False)
    state.set_duty_status(1, 1, True)

    network_perf = state.calc_network_perf(0, 1)

    assert network_perf == 0.5


def test_state_load():
    orig = State(
        [
            AttestationSequence(1),
            AttestationSequence(1),
        ]
    )

    orig.data[0].set_duty_status(0, AttestationStatus.INCLUDED)
    orig.data[1].set_duty_status(0, AttestationStatus.MISSED)

    orig.commit()
    copy = State.load()
    for orig_seq, copy_seq in zip(orig.data, copy.data):
        assert str(orig_seq) == str(copy_seq)


def test_state_clear():
    state = State(
        [
            AttestationSequence(43),
            AttestationSequence(43),
        ]
    )

    state._epochs_to_process = {EpochNumber(1), EpochNumber(33)}
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
    frame_epochs_count = 10

    first_validator = AttestationSequence(5)

    second_validator = AttestationSequence(5)
    second_validator.set_duty_status(0, AttestationStatus.MISSED)
    second_validator.set_duty_status(1, AttestationStatus.INCLUDED)

    third_validator = AttestationSequence(5)

    state = State(
        [
            first_validator,
            second_validator,
        ]
    )
    state._epochs_to_process = tuple(EpochNumber(epoch) for epoch in range(frame_epochs_count))

    state.set_duty_status(EpochNumber(0), ValidatorIndex(0), True)
    state.set_duty_status(EpochNumber(1), ValidatorIndex(0), False)

    state.set_duty_status(EpochNumber(2), ValidatorIndex(1), True)
    state.set_duty_status(EpochNumber(3), ValidatorIndex(1), True)
    state.set_duty_status(EpochNumber(4), ValidatorIndex(1), False)

    state.set_duty_status(EpochNumber(0), ValidatorIndex(2), True)
    state.set_duty_status(EpochNumber(1), ValidatorIndex(2), False)

    assert state.data[0].get_duty_status(0) == AttestationStatus.INCLUDED
    assert state.data[0].get_duty_status(1) == AttestationStatus.MISSED

    assert state.data[1].get_duty_status(0) == AttestationStatus.MISSED
    assert state.data[1].get_duty_status(1) == AttestationStatus.INCLUDED
    assert state.data[1].get_duty_status(2) == AttestationStatus.INCLUDED
    assert state.data[1].get_duty_status(3) == AttestationStatus.INCLUDED
    assert state.data[1].get_duty_status(4) == AttestationStatus.MISSED

    assert state.data[2].get_duty_status(0) == AttestationStatus.INCLUDED
    assert state.data[2].get_duty_status(1) == AttestationStatus.MISSED

    assert state.data[0].count_missed() == 1
    assert state.data[0].count_included() == 1

    assert state.data[1].count_missed() == 2
    assert state.data[1].count_included() == 3

    assert state.data[2].count_missed() == 1
    assert state.data[2].count_included() == 1


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

        state.migrate(l_epoch, r_epoch)

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
        state._migrate_data = Mock(side_effect=state._migrate_data)
        state.migrate(l_epoch_old, r_epoch_old)
        state.clear.assert_not_called()

        state.migrate(l_epoch_new, r_epoch_new)
        state.clear.assert_called_once()
        state._migrate_data.assert_not_called()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))

    @pytest.mark.parametrize(
        ("l_epoch_old", "r_epoch_old", "l_epoch_new", "r_epoch_new"),
        [
            pytest.param(1, 255, 1, 510, id="Migrate Aa..b..B"),
            pytest.param(32, 510, 1, 510, id="Migrate: A..a..bB"),
            pytest.param(32, 255, 1, 510, id="Migrate: A..a..b..B"),
        ],
    )
    def test_new_frame_extends_old_state(self, l_epoch_old, r_epoch_old, l_epoch_new, r_epoch_new):
        state = State()
        state.clear = Mock(side_effect=state.clear)

        state.migrate(l_epoch_old, r_epoch_old)
        state.clear.assert_not_called()

        state.migrate(l_epoch_new, r_epoch_new)
        state.clear.assert_not_called()

        assert state.unprocessed_epochs == set(sequence(l_epoch_new, r_epoch_new))

    @pytest.mark.parametrize(
        ("l_epoch_old", "r_epoch_old", "l_epoch_new", "r_epoch_new"),
        [
            pytest.param(1, 255, 1, 510, id="Migrate Aa..b..B"),
            pytest.param(32, 510, 1, 510, id="Migrate: A..a..bB"),
            pytest.param(32, 255, 1, 510, id="Migrate: A..a..b..B"),
        ],
    )
    def test_new_frame_extends_old_state_data_migration(self, l_epoch_old, r_epoch_old, l_epoch_new, r_epoch_new):
        state = State()
        state.clear = Mock(side_effect=state.clear)

        state.migrate(l_epoch_old, r_epoch_old)
        state.clear.assert_not_called()

        for epoch in sequence(l_epoch_old, r_epoch_old):
            state.add_processed_epoch(epoch)
            for i in range(3):
                state.set_duty_status(epoch, ValidatorIndex(i), True)

        state.migrate(l_epoch_new, r_epoch_new)
        state.clear.assert_not_called()

        assert state.unprocessed_epochs == (set(sequence(l_epoch_new, r_epoch_new)) - set(sequence(l_epoch_old, r_epoch_old)))
        for epoch in sequence(l_epoch_old, r_epoch_old):
            for i in range(3):
                assert state.get_duty_status(epoch, ValidatorIndex(i)) == AttestationStatus.INCLUDED
