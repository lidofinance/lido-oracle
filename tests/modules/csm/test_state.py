from collections import defaultdict

import pytest

from src.modules.oracles.staking_modules.common.state import DutyAccumulator, InvalidState, NetworkDuties, State
from src.types import EpochNumber, ValidatorIndex


def make_state(l_epoch: int = 0, r_epoch: int = 31, epochs_per_frame: int = 32) -> State:
    return State(EpochNumber(l_epoch), EpochNumber(r_epoch), epochs_per_frame)


@pytest.mark.unit
def test_init__single_frame_range__creates_empty_frame_data():
    state = make_state(0, 31, 32)

    assert state.data == {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(attestations={}, proposals={}, syncs={}),
    }
    assert state.frames == [(EpochNumber(0), EpochNumber(31))]
    assert not state.is_fulfilled


@pytest.mark.unit
def test_init__multiple_frame_range__creates_empty_frame_data_per_frame():
    state = make_state(0, 63, 32)

    assert state.data == {
        (EpochNumber(0), EpochNumber(31)): NetworkDuties(attestations={}, proposals={}, syncs={}),
        (EpochNumber(32), EpochNumber(63)): NetworkDuties(attestations={}, proposals={}, syncs={}),
    }
    assert state.frames == [(EpochNumber(0), EpochNumber(31)), (EpochNumber(32), EpochNumber(63))]
    assert not state.is_fulfilled


@pytest.mark.unit
def test_calculate_frames__exact_frame_size__returns_frames():
    epochs = tuple(EpochNumber(e) for e in range(10))

    frames = State._calculate_frames(epochs, 5)

    assert frames == [(EpochNumber(0), EpochNumber(4)), (EpochNumber(5), EpochNumber(9))]


@pytest.mark.unit
def test_calculate_frames__insufficient_epochs__raises_error():
    epochs = tuple(EpochNumber(e) for e in range(8))

    with pytest.raises(ValueError, match="Insufficient epochs to form a frame"):
        State._calculate_frames(epochs, 5)


@pytest.mark.unit
def test_save_duties__existing_frame__merges_data():
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    state.data[frame].attestations[ValidatorIndex(1)] = DutyAccumulator(assigned=10, included=8)
    duties = NetworkDuties(
        attestations=defaultdict(DutyAccumulator, {ValidatorIndex(1): DutyAccumulator(assigned=2, included=1)}),
        proposals=defaultdict(DutyAccumulator, {ValidatorIndex(2): DutyAccumulator(assigned=1, included=1)}),
        syncs=defaultdict(DutyAccumulator, {ValidatorIndex(3): DutyAccumulator(assigned=4, included=3)}),
    )

    state.save_duties(frame, duties)

    assert state.data[frame].attestations == {ValidatorIndex(1): DutyAccumulator(assigned=12, included=9)}
    assert state.data[frame].proposals == {ValidatorIndex(2): DutyAccumulator(assigned=1, included=1)}
    assert state.data[frame].syncs == {ValidatorIndex(3): DutyAccumulator(assigned=4, included=3)}


@pytest.mark.unit
def test_save_duties__missing_frame__raises_error():
    state = make_state()

    with pytest.raises(InvalidState, match="No data for frame"):
        state.save_duties((EpochNumber(32), EpochNumber(63)), NetworkDuties())


@pytest.mark.unit
def test_attestation_aggregate_perf():
    aggr = DutyAccumulator(included=333, assigned=777)

    assert aggr.perf == pytest.approx(0.4285, abs=1e-4)


@pytest.mark.unit
def test_get_validator_duties():
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    state.data = {
        frame: NetworkDuties(
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

    duties = state.get_validator_duties(frame, ValidatorIndex(1))

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
def test_get_validator_duties__missing_frame__raises_error():
    state = make_state()

    with pytest.raises(InvalidState, match="No data for frame"):
        state.get_validator_duties((EpochNumber(32), EpochNumber(63)), ValidatorIndex(1))


@pytest.mark.unit
def test_get_att_network_aggr_computes_correctly():
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    state.data = {
        frame: NetworkDuties(
            attestations=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }

    aggr = state.get_att_network_aggr(frame)

    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_sync_network_aggr_computes_correctly():
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    state.data = {
        frame: NetworkDuties(
            syncs=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }

    aggr = state.get_sync_network_aggr(frame)

    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
def test_get_prop_network_aggr_computes_correctly():
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    state.data = {
        frame: NetworkDuties(
            proposals=defaultdict(
                DutyAccumulator,
                {ValidatorIndex(1): DutyAccumulator(10, 5), ValidatorIndex(2): DutyAccumulator(20, 15)},
            )
        )
    }

    aggr = state.get_prop_network_aggr(frame)

    assert aggr.assigned == 30
    assert aggr.included == 20


@pytest.mark.unit
@pytest.mark.parametrize(
    "duties_field, aggr_method",
    [
        pytest.param("attestations", "get_att_network_aggr", id="attestations"),
        pytest.param("proposals", "get_prop_network_aggr", id="proposals"),
        pytest.param("syncs", "get_sync_network_aggr", id="syncs"),
    ],
)
def test_get_network_aggr__invalid_accumulator__raises_error(duties_field: str, aggr_method: str):
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    frame_data = NetworkDuties()
    getattr(frame_data, duties_field)[ValidatorIndex(1)] = DutyAccumulator(assigned=10, included=15)
    state.data = {frame: frame_data}

    with pytest.raises(InvalidState, match="Invalid accumulator"):
        getattr(state, aggr_method)(frame)


@pytest.mark.unit
@pytest.mark.parametrize(
    "aggr_method",
    [
        pytest.param("get_att_network_aggr", id="attestations"),
        pytest.param("get_prop_network_aggr", id="proposals"),
        pytest.param("get_sync_network_aggr", id="syncs"),
    ],
)
def test_get_network_aggr__missing_frame__raises_error(aggr_method: str):
    state = make_state()

    with pytest.raises(InvalidState, match="No data for frame"):
        getattr(state, aggr_method)((EpochNumber(32), EpochNumber(63)))


@pytest.mark.unit
@pytest.mark.parametrize(
    "aggr_method",
    [
        pytest.param("get_att_network_aggr", id="attestations"),
        pytest.param("get_prop_network_aggr", id="proposals"),
        pytest.param("get_sync_network_aggr", id="syncs"),
    ],
)
def test_get_network_aggr__empty_frame_data__returns_zero_accumulator(aggr_method: str):
    state = make_state()
    frame = (EpochNumber(0), EpochNumber(31))
    state.data = {frame: NetworkDuties()}

    aggr = getattr(state, aggr_method)(frame)

    assert aggr.assigned == 0
    assert aggr.included == 0
