from pathlib import Path
from unittest.mock import Mock

import pytest

from src.modules.csm.state import AttestationsAggregate, State
from src.types import EpochNumber, ValidatorIndex
from src.utils.range import sequence


@pytest.fixture()
def state_file_path(tmp_path: Path) -> Path:
    return (tmp_path / "mock").with_suffix(State.EXTENSION)


@pytest.fixture(autouse=True)
def mock_state_file(state_file_path: Path):
    State.file = Mock(return_value=state_file_path)


def test_attestation_aggregate_perf():
    aggr = AttestationsAggregate(included=333, assigned=777)
    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


def test_state_avg_perf():
    state = State()

    assert state.avg_perf == 0

    state = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=0, assigned=0),
            ValidatorIndex(1): AttestationsAggregate(included=0, assigned=0),
        }
    )

    # assert state.avg_perf == 0

    state = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAggregate(included=167, assigned=223),
        }
    )

    assert state.avg_perf == 0.5


def test_state_attestations():
    state = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAggregate(included=167, assigned=223),
        }
    )

    network_aggr = state.network_aggr

    assert network_aggr.assigned == 1000
    assert network_aggr.included == 500


def test_state_load():
    orig = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAggregate(included=167, assigned=223),
        }
    )

    orig.commit()
    copy = State.load()
    assert copy == orig


def test_state_clear():
    state = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=333, assigned=777),
            ValidatorIndex(1): AttestationsAggregate(included=167, assigned=223),
        }
    )

    state._epochs_to_process = {EpochNumber(1), EpochNumber(33)}
    state._processed_epochs = {EpochNumber(42), EpochNumber(17)}

    state.clear()
    assert state.is_empty
    assert state == State()


def test_state_add_processed_epoch():
    state = State()
    state.add_processed_epoch(EpochNumber(42))
    state.add_processed_epoch(EpochNumber(17))
    assert state._processed_epochs == {EpochNumber(42), EpochNumber(17)}


def test_state_inc():
    state = State(
        {
            ValidatorIndex(0): AttestationsAggregate(included=0, assigned=0),
            ValidatorIndex(1): AttestationsAggregate(included=1, assigned=2),
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
        AttestationsAggregate(included=1, assigned=2),
        AttestationsAggregate(included=3, assigned=5),
        AttestationsAggregate(included=1, assigned=2),
    )


def test_state_file_is_path():
    assert isinstance(State.file(), Path)

