from copy import deepcopy
from typing import cast
from unittest.mock import Mock, patch

import pytest

import src.modules.csm.checkpoint as checkpoint_module
from src.constants import EPOCHS_PER_SYNC_COMMITTEE_PERIOD
from src.modules.csm.checkpoint import (
    FrameCheckpoint,
    FrameCheckpointProcessor,
    FrameCheckpointsIterator,
    MinStepIsNotReached,
    SlotNumber,
    SlotOutOfRootsRange,
    SyncCommitteesCache,
    ValidatorDuty,
    process_attestations,
)
from src.modules.csm.state import State
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BeaconSpecResponse, BlockAttestation, SlotAttestationCommittee, SyncCommittee
from src.types import BlockRoot, EpochNumber, ValidatorIndex
from src.utils.web3converter import Web3Converter
from tests.factory.bitarrays import BitListFactory
from tests.factory.configs import (
    BeaconSpecResponseFactory,
    BlockAttestationFactory,
    ChainConfigFactory,
    FrameConfigFactory,
    SlotAttestationCommitteeFactory,
)


@pytest.fixture(autouse=True)
def no_commit(monkeypatch):
    monkeypatch.setattr(State, "commit", Mock())


@pytest.fixture
def frame_config() -> FrameConfig:
    return FrameConfigFactory.build(
        epochs_per_frame=225,
    )


@pytest.fixture
def chain_config() -> ChainConfig:
    return ChainConfigFactory.build(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )


@pytest.fixture
def converter(frame_config: FrameConfig, chain_config: ChainConfig) -> Web3Converter:
    return Web3Converter(chain_config, frame_config)


@pytest.fixture
def sync_committees_cache():
    with patch('src.modules.csm.checkpoint.SYNC_COMMITTEES_CACHE', SyncCommitteesCache()) as cache:
        yield cache


@pytest.mark.unit
def test_checkpoints_iterator_min_epoch_is_not_reached(converter):
    with pytest.raises(MinStepIsNotReached):
        FrameCheckpointsIterator(converter, 100, 600, 109)


@pytest.mark.unit
@pytest.mark.parametrize(
    "l_epoch,r_epoch,finalized_epoch,expected_checkpoints",
    [
        (0, 254, 253, [FrameCheckpoint(253 * 32, tuple(range(0, 252)))]),
        (0, 254, 254, [FrameCheckpoint(254 * 32, tuple(range(0, 253)))]),
        (0, 254, 255, [FrameCheckpoint(255 * 32, tuple(range(0, 254)))]),
        (
            # fit to max checkpoint step, can generate full checkpoint (with 255 epochs)
            0,
            254,
            256,
            [FrameCheckpoint(256 * 32, tuple(range(0, 255)))],
        ),
        (
            # fit to max checkpoint step, and first 15 epochs is processed
            15,
            254,
            256,
            [FrameCheckpoint(256 * 32, tuple(range(15, 255)))],
        ),
        (
            # fit to min checkpoint step, and first 15 epochs is processed
            15,
            255,
            27,
            [FrameCheckpoint(27 * 32, tuple(range(15, 26)))],
        ),
        (
            0,
            255 * 2,
            255 * 2 + 2,
            [
                FrameCheckpoint(8192, tuple(range(0, 255))),
                FrameCheckpoint(16352, tuple(range(255, 510))),
                FrameCheckpoint(16384, tuple(range(510, 511))),
            ],
        ),
        (
            0,
            225 * 3,
            225 * 3 + 2,
            [
                FrameCheckpoint(8192, tuple(range(0, 255))),
                FrameCheckpoint(16352, tuple(range(255, 510))),
                FrameCheckpoint(21664, tuple(range(510, 676))),
            ],
        ),
    ],
)
def test_checkpoints_iterator_given_checkpoints(converter, l_epoch, r_epoch, finalized_epoch, expected_checkpoints):
    iterator = FrameCheckpointsIterator(converter, l_epoch, r_epoch, finalized_epoch)
    assert list(iter(iterator)) == expected_checkpoints


@pytest.fixture
def consensus_client():
    return ConsensusClient('http://localhost/', 5 * 60, 5, 5)


@pytest.fixture
def missing_slots():
    return set()


@pytest.fixture
def mock_get_state_block_roots(consensus_client, missing_slots):
    def _get_state_block_roots(state_id: int):
        roots_count = 8192
        br = [checkpoint_module.ZERO_BLOCK_ROOT] * roots_count
        for i in range(min(roots_count, state_id), 0, -1):
            slot = state_id - i
            index = slot % roots_count
            prev_slot_index = (slot - 1) % roots_count
            br[index] = br[prev_slot_index] if slot in missing_slots else f"0x{slot}"
        oldest_slot = max(state_id - roots_count, 0)
        oldest_slot_index = oldest_slot % roots_count
        br[oldest_slot_index] = f"0x{max(oldest_slot - 1, 0)}" if oldest_slot in missing_slots else f"0x{oldest_slot}"
        return br

    def _get_block_header(state_id: str):
        return Mock(
            data=Mock(header=Mock(message=Mock(slot=int(state_id.split('0x')[1])))),
        )

    consensus_client.get_state_block_roots = Mock(side_effect=_get_state_block_roots)
    consensus_client.get_block_header = Mock(side_effect=_get_block_header)


@pytest.mark.unit
@pytest.mark.parametrize(
    "state_id, missing_slots, expected_existing_roots_count",
    [
        pytest.param(5, set(), 5, id="chain before 8192 slots"),
        pytest.param(15, {1, 3}, 13, id="missing slots in chain before 8192 slots"),
        pytest.param(8192, set(), 8192, id="all slots present"),
        pytest.param(8192, {8191}, 8191, id="last slot is missing"),
        pytest.param(8192, {100, 2543, 3666, 4444, 8191}, 8187, id="multiple missing slots"),
        pytest.param(8192, {1000, 1001, 1002, 1003, 1004, 1005}, 8186, id="multiple missing slots in a row"),
        pytest.param(8192, {8193}, 8192, id="future missing slot"),
        pytest.param(100500, {11}, 8192, id="past missing slot"),
        pytest.param(15000, {15000 - 8192}, 8191, id="the oldest slot is missing"),
    ],
)
def test_checkpoints_processor_get_block_roots(
    consensus_client, mock_get_state_block_roots, converter: Web3Converter, state_id, expected_existing_roots_count
):
    state = ...
    finalized_blockstamp = ...
    processor = FrameCheckpointProcessor(
        consensus_client,
        converter,
        state,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(state_id)
    assert len([r for r in roots if r is not None]) == expected_existing_roots_count


@pytest.fixture
def mock_get_config_spec(consensus_client):
    bc_spec = cast(BeaconSpecResponse, BeaconSpecResponseFactory.build())
    bc_spec.SLOTS_PER_HISTORICAL_ROOT = 8192
    consensus_client.get_config_spec = Mock(return_value=bc_spec)


@pytest.mark.unit
def test_checkpoints_processor_select_block_roots(
    consensus_client, mock_get_state_block_roots, mock_get_config_spec, converter: Web3Converter
):
    state = ...
    finalized_blockstamp = ...
    processor = FrameCheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(8192)
    selected = processor._select_block_roots(roots, 10, 8192)
    duty_epoch_roots, next_epoch_roots = selected
    assert len(duty_epoch_roots) == 32
    assert len(next_epoch_roots) == 32
    assert duty_epoch_roots == [(r, f'0x{r}') for r in range(320, 352)]
    assert next_epoch_roots == [(r, f'0x{r}') for r in range(352, 384)]


@pytest.mark.unit
def test_checkpoints_processor_select_block_roots_out_of_range(
    consensus_client, mock_get_state_block_roots, mock_get_config_spec, converter: Web3Converter
):
    state = ...
    finalized_blockstamp = ...
    processor = FrameCheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(8192)
    with pytest.raises(checkpoint_module.SlotOutOfRootsRange, match="Slot is out of the state block roots range"):
        processor._select_block_roots(roots, 255, 8192)


@pytest.fixture()
def mock_get_attestation_committees(consensus_client):
    def _get_attestation_committees(finalized_slot, epoch):
        committees = []
        validators = [ValidatorIndex(v) for v in range(0, 2048 * 32)]
        for slot in range(epoch * 32, epoch * 32 + 32):  # 1 epoch = 32 slots.
            for committee_idx in range(0, 64):  # 64 committees per slot
                committee = deepcopy(cast(SlotAttestationCommittee, SlotAttestationCommitteeFactory.build()))
                committee.slot = SlotNumber(slot)
                committee.index = committee_idx
                # 32 validators per committee
                committee.validators = [validators.pop() for _ in range(32)]
                committees.append(committee)
        return committees

    consensus_client.get_attestation_committees = Mock(side_effect=_get_attestation_committees)


@pytest.mark.unit
def test_checkpoints_processor_prepare_committees(mock_get_attestation_committees, consensus_client, converter):
    state = ...
    finalized_blockstamp = ...
    processor = FrameCheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    raw = consensus_client.get_attestation_committees(0, 0)
    committees = processor._prepare_attestation_duties(0)
    assert len(committees) == 2048
    for index, (committee_id, validators) in enumerate(committees.items()):
        slot, committee_index = committee_id
        committee_from_raw = raw[index]
        assert slot == committee_from_raw.slot
        assert committee_index == committee_from_raw.index
        assert len(validators) == 32
        for validator in validators:
            assert validator.included is False


@pytest.mark.unit
def test_checkpoints_processor_process_attestations(mock_get_attestation_committees, consensus_client, converter):
    state = ...
    finalized_blockstamp = ...
    processor = FrameCheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    committees = processor._prepare_attestation_duties(0)
    # normal attestation
    attestation = cast(BlockAttestation, BlockAttestationFactory.build())
    attestation.data.slot = 0
    attestation.data.index = 0
    attestation.aggregation_bits = BitListFactory.build(set_indices=[i for i in range(32)]).hex()
    # the same but with no included attestations in bits
    attestation2 = cast(BlockAttestation, BlockAttestationFactory.build())
    attestation2.data.slot = 0
    attestation2.data.index = 0
    attestation2.aggregation_bits = BitListFactory.build(set_indices=[]).hex()
    process_attestations([attestation, attestation2], committees)
    for index, validators in enumerate(committees.values()):
        for validator in validators:
            # only the first attestation is accounted
            # slot = 0 and committee = 0
            if index == 0:
                assert validator.included is True
            else:
                assert validator.included is False


@pytest.mark.unit
def test_checkpoints_processor_process_attestations_undefined_committee(
    mock_get_attestation_committees, consensus_client, converter
):
    state = ...
    finalized_blockstamp = ...
    processor = FrameCheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    committees = processor._prepare_attestation_duties(0)
    # undefined committee
    attestation = cast(BlockAttestation, BlockAttestationFactory.build())
    attestation.data.slot = 100500
    attestation.data.index = 100500
    attestation.aggregation_bits = '0x' + 'f' * 32
    process_attestations([attestation], committees)
    for validators in committees.values():
        for v in validators:
            assert v.included is False


@pytest.fixture
def frame_checkpoint_processor():
    cc = Mock()
    state = Mock()
    converter = Mock()
    finalized_blockstamp = Mock(slot_number=SlotNumber(0))
    return FrameCheckpointProcessor(cc, state, converter, finalized_blockstamp)


@pytest.mark.unit
def test_check_duties_processes_epoch_with_attestations_and_sync_committee(frame_checkpoint_processor):
    checkpoint_block_roots = [Mock(spec=BlockRoot), None, Mock(spec=BlockRoot)]
    checkpoint_slot = SlotNumber(100)
    duty_epoch = EpochNumber(10)
    duty_epoch_roots = [(SlotNumber(100), Mock(spec=BlockRoot)), (SlotNumber(101), Mock(spec=BlockRoot))]
    next_epoch_roots = [(SlotNumber(102), Mock(spec=BlockRoot)), (SlotNumber(103), Mock(spec=BlockRoot))]
    frame_checkpoint_processor._prepare_attestation_duties = Mock(
        return_value={SlotNumber(100): [ValidatorDuty(1, False)]}
    )
    frame_checkpoint_processor._prepare_propose_duties = Mock(
        return_value={SlotNumber(100): ValidatorDuty(1, False), SlotNumber(101): ValidatorDuty(1, False)}
    )
    frame_checkpoint_processor._prepare_sync_committee_duties = Mock(
        return_value={
            100: [ValidatorDuty(1, False) for _ in range(32)],
            101: [ValidatorDuty(1, False) for _ in range(32)],
        }
    )

    attestation = Mock()
    attestation.data.slot = SlotNumber(100)
    attestation.data.index = 0
    attestation.aggregation_bits = "0xff"
    attestation.committee_bits = "0xff"

    sync_aggregate = Mock()
    sync_aggregate.sync_committee_bits = "0xff"

    frame_checkpoint_processor.cc.get_block_attestations_and_sync = Mock(return_value=([attestation], sync_aggregate))
    frame_checkpoint_processor.state.unprocessed_epochs = [duty_epoch]

    frame_checkpoint_processor._check_duties(
        checkpoint_block_roots, checkpoint_slot, duty_epoch, duty_epoch_roots, next_epoch_roots
    )

    frame_checkpoint_processor.state.save_att_duty.assert_called()
    frame_checkpoint_processor.state.save_sync_duty.assert_called()
    frame_checkpoint_processor.state.save_prop_duty.assert_called()


@pytest.mark.unit
def test_check_duties_processes_epoch_with_no_attestations(frame_checkpoint_processor):
    checkpoint_block_roots = [Mock(spec=BlockRoot), None, Mock(spec=BlockRoot)]
    checkpoint_slot = SlotNumber(100)
    duty_epoch = EpochNumber(10)
    duty_epoch_roots = [(SlotNumber(100), Mock(spec=BlockRoot)), (SlotNumber(101), Mock(spec=BlockRoot))]
    next_epoch_roots = [(SlotNumber(102), Mock(spec=BlockRoot)), (SlotNumber(103), Mock(spec=BlockRoot))]
    frame_checkpoint_processor._prepare_attestation_duties = Mock(return_value={})
    frame_checkpoint_processor._prepare_propose_duties = Mock(
        return_value={SlotNumber(100): ValidatorDuty(1, False), SlotNumber(101): ValidatorDuty(1, False)}
    )
    frame_checkpoint_processor._prepare_sync_committee_duties = Mock(
        return_value={100: [ValidatorDuty(1, False)], 101: [ValidatorDuty(1, False)]}
    )

    sync_aggregate = Mock()
    sync_aggregate.sync_committee_bits = "0x00"

    frame_checkpoint_processor.cc.get_block_attestations_and_sync = Mock(return_value=([], sync_aggregate))
    frame_checkpoint_processor.state.unprocessed_epochs = [duty_epoch]

    frame_checkpoint_processor._check_duties(
        checkpoint_block_roots, checkpoint_slot, duty_epoch, duty_epoch_roots, next_epoch_roots
    )

    assert frame_checkpoint_processor.state.save_att_duty.call_count == 0
    assert frame_checkpoint_processor.state.save_sync_duty.call_count == 2
    assert frame_checkpoint_processor.state.save_prop_duty.call_count == 2


@pytest.mark.unit
def test_prepare_sync_committee_returns_duties_for_valid_sync_committee(frame_checkpoint_processor):
    epoch = EpochNumber(10)
    duty_block_roots = [(SlotNumber(100), Mock()), (SlotNumber(101), Mock())]
    sync_committee = Mock(spec=SyncCommittee)
    sync_committee.validators = [1, 2, 3]
    frame_checkpoint_processor._get_sync_committee = Mock(return_value=sync_committee)

    duties = frame_checkpoint_processor._prepare_sync_committee_duties(epoch, duty_block_roots)

    expected_duties = {
        SlotNumber(100): [
            ValidatorDuty(validator_index=1, included=False),
            ValidatorDuty(validator_index=2, included=False),
            ValidatorDuty(validator_index=3, included=False),
        ],
        SlotNumber(101): [
            ValidatorDuty(validator_index=1, included=False),
            ValidatorDuty(validator_index=2, included=False),
            ValidatorDuty(validator_index=3, included=False),
        ],
    }
    assert duties == expected_duties


@pytest.mark.unit
def test_prepare_sync_committee_skips_duties_for_missed_slots(frame_checkpoint_processor):
    epoch = EpochNumber(10)
    duty_block_roots = [(SlotNumber(100), None), (SlotNumber(101), Mock())]
    sync_committee = Mock(spec=SyncCommittee)
    sync_committee.validators = [1, 2, 3]
    frame_checkpoint_processor._get_sync_committee = Mock(return_value=sync_committee)

    duties = frame_checkpoint_processor._prepare_sync_committee_duties(epoch, duty_block_roots)

    expected_duties = {
        SlotNumber(101): [
            ValidatorDuty(validator_index=1, included=False),
            ValidatorDuty(validator_index=2, included=False),
            ValidatorDuty(validator_index=3, included=False),
        ]
    }
    assert duties == expected_duties


@pytest.mark.unit
def test_get_sync_committee_returns_cached_sync_committee(
    frame_checkpoint_processor, sync_committees_cache: SyncCommitteesCache
):
    epoch = EpochNumber(10)
    sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
    cached_sync_committee = Mock(spec=SyncCommittee)
    sync_committees_cache[sync_committee_period] = cached_sync_committee

    result = frame_checkpoint_processor._get_sync_committee(epoch)
    assert result == cached_sync_committee


@pytest.mark.unit
def test_get_sync_committee_fetches_and_caches_when_not_cached(
    frame_checkpoint_processor, sync_committees_cache: SyncCommitteesCache
):
    epoch = EpochNumber(10)
    sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
    sync_committee = Mock(spec=SyncCommittee)
    sync_committee.validators = [1, 2, 3]
    frame_checkpoint_processor.converter.get_epoch_first_slot = Mock(return_value=SlotNumber(0))
    frame_checkpoint_processor.cc.get_sync_committee = Mock(return_value=sync_committee)

    prev_slot_response = Mock()
    prev_slot_response.message.slot = SlotNumber(0)
    prev_slot_response.message.body.execution_payload.block_hash = "0x00"
    with patch('src.modules.csm.checkpoint.get_prev_non_missed_slot', Mock(return_value=prev_slot_response)):
        result = frame_checkpoint_processor._get_sync_committee(epoch)

    assert result.validators == sync_committee.validators
    assert sync_committees_cache[sync_committee_period].validators == sync_committee.validators


@pytest.mark.unit
def test_get_sync_committee_handles_cache_eviction(
    frame_checkpoint_processor, sync_committees_cache: SyncCommitteesCache
):
    epoch = EpochNumber(10)
    sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
    old_sync_committee_period = sync_committee_period - 1
    old_sync_committee = Mock(spec=SyncCommittee)
    sync_committee = Mock(spec=SyncCommittee)
    frame_checkpoint_processor.cc.get_sync_committee = Mock(return_value=sync_committee)

    sync_committees_cache.max_size = 1
    sync_committees_cache[old_sync_committee_period] = old_sync_committee

    prev_slot_response = Mock()
    prev_slot_response.message.slot = SlotNumber(0)
    prev_slot_response.message.body.execution_payload.block_hash = "0x00"
    with patch('src.modules.csm.checkpoint.get_prev_non_missed_slot', Mock(return_value=prev_slot_response)):
        result = frame_checkpoint_processor._get_sync_committee(epoch)

    assert result == sync_committee
    assert sync_committee_period in sync_committees_cache
    assert old_sync_committee_period not in sync_committees_cache


@pytest.mark.unit
def test_prepare_propose_duties(frame_checkpoint_processor):
    epoch = EpochNumber(10)
    checkpoint_block_roots = [Mock(spec=BlockRoot), None, Mock(spec=BlockRoot)]
    checkpoint_slot = SlotNumber(100)
    dependent_root = Mock(spec=BlockRoot)
    frame_checkpoint_processor._get_dependent_root_for_proposer_duties = Mock(return_value=dependent_root)
    proposer_duty1 = Mock(slot=SlotNumber(101), validator_index=1)
    proposer_duty2 = Mock(slot=SlotNumber(102), validator_index=2)
    frame_checkpoint_processor.cc.get_proposer_duties = Mock(return_value=[proposer_duty1, proposer_duty2])

    duties = frame_checkpoint_processor._prepare_propose_duties(epoch, checkpoint_block_roots, checkpoint_slot)

    expected_duties = {
        SlotNumber(101): ValidatorDuty(validator_index=1, included=False),
        SlotNumber(102): ValidatorDuty(validator_index=2, included=False),
    }
    assert duties == expected_duties


@pytest.mark.unit
def test_get_dependent_root_for_proposer_duties_from_state_block_roots(frame_checkpoint_processor):
    epoch = EpochNumber(10)
    checkpoint_block_roots = [Mock(spec=BlockRoot), None, Mock(spec=BlockRoot)]
    checkpoint_slot = SlotNumber(100)
    dependent_slot = SlotNumber(99)
    frame_checkpoint_processor.converter.get_epoch_last_slot = Mock(return_value=dependent_slot)
    frame_checkpoint_processor._select_block_root_by_slot = Mock(return_value=checkpoint_block_roots[2])

    dependent_root = frame_checkpoint_processor._get_dependent_root_for_proposer_duties(
        epoch, checkpoint_block_roots, checkpoint_slot
    )

    assert dependent_root == checkpoint_block_roots[2]


@pytest.mark.unit
def test_get_dependent_root_for_proposer_duties_from_cl_when_slot_out_of_range(frame_checkpoint_processor):
    epoch = EpochNumber(10)
    checkpoint_block_roots = [Mock(spec=BlockRoot), None, Mock(spec=BlockRoot)]
    checkpoint_slot = SlotNumber(100)
    dependent_slot = SlotNumber(99)
    frame_checkpoint_processor.converter.get_epoch_last_slot = Mock(return_value=dependent_slot)
    frame_checkpoint_processor._select_block_root_by_slot = Mock(side_effect=SlotOutOfRootsRange)
    non_missed_slot = SlotNumber(98)

    prev_slot_response = Mock()
    prev_slot_response.message.slot = non_missed_slot
    with patch('src.modules.csm.checkpoint.get_prev_non_missed_slot', Mock(return_value=prev_slot_response)):
        frame_checkpoint_processor.cc.get_block_root = Mock(return_value=Mock(root=checkpoint_block_roots[0]))

        dependent_root = frame_checkpoint_processor._get_dependent_root_for_proposer_duties(
            epoch, checkpoint_block_roots, checkpoint_slot
        )

        assert dependent_root == checkpoint_block_roots[0]
