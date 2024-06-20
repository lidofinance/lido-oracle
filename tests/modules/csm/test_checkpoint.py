from copy import deepcopy
from typing import cast, Iterator
from unittest.mock import Mock

import pytest

from src.modules.csm.checkpoint import (
    CheckpointsIterator,
    Checkpoint,
    CheckpointProcessor,
    process_attestations,
    MinStepIsNotReached,
)
from src.modules.csm.state import State
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BeaconSpecResponse, SlotAttestationCommittee, BlockAttestation
from src.utils.web3converter import Web3Converter
from tests.factory.configs import (
    FrameConfigFactory,
    ChainConfigFactory,
    BeaconSpecResponseFactory,
    SlotAttestationCommitteeFactory,
    BlockAttestationFactory,
)


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


def test_checkpoints_iterator_min_epoch_is_not_reached(converter):
    with pytest.raises(MinStepIsNotReached):
        CheckpointsIterator(converter, 100, 600, 109)


@pytest.mark.parametrize(
    "l_epoch,r_epoch,finalized_epoch,expected_checkpoints",
    [
        (0, 254, 253, [Checkpoint(253 * 32, tuple(range(0, 252)))]),
        (0, 254, 254, [Checkpoint(254 * 32, tuple(range(0, 253)))]),
        (0, 254, 255, [Checkpoint(255 * 32, tuple(range(0, 254)))]),
        (
            # fit to max checkpoint step, can generate full checkpoint (with 255 epochs)
            0,
            254,
            256,
            [Checkpoint(256 * 32, tuple(range(0, 255)))],
        ),
        (
            # fit to max checkpoint step, and first 15 epochs is processed
            15,
            254,
            256,
            [Checkpoint(256 * 32, tuple(range(15, 255)))],
        ),
        (
            # fit to min checkpoint step, and first 15 epochs is processed
            15,
            255,
            27,
            [Checkpoint(27 * 32, tuple(range(15, 26)))],
        ),
        (
            0,
            255 * 2,
            255 * 2 + 2,
            [
                Checkpoint(8192, tuple(range(0, 255))),
                Checkpoint(16352, tuple(range(255, 510))),
                Checkpoint(16384, tuple(range(510, 511))),
            ],
        ),
        (
            0,
            225 * 3,
            225 * 3 + 2,
            [
                Checkpoint(8192, tuple(range(0, 255))),
                Checkpoint(16352, tuple(range(255, 510))),
                Checkpoint(21664, tuple(range(510, 676))),
            ],
        ),
    ],
)
def test_checkpoints_iterator_given_checkpoints(converter, l_epoch, r_epoch, finalized_epoch, expected_checkpoints):
    iterator = CheckpointsIterator(converter, l_epoch, r_epoch, finalized_epoch)
    assert list(iter(iterator)) == expected_checkpoints


@pytest.fixture
def consensus_client():
    return ConsensusClient('http://localhost', 5 * 60, 5, 5)


@pytest.fixture
def mock_get_state_block_roots(consensus_client):
    def _get_state_block_roots(state_id):
        return [f'0x{r}' for r in range(state_id, state_id + 8192)]

    consensus_client.get_state_block_roots = Mock(side_effect=_get_state_block_roots)


@pytest.fixture
def mock_get_state_block_roots_with_duplicates(consensus_client):
    def _get_state_block_roots(state_id):
        br = [f'0x{r}' for r in range(0, 8192)]
        return [br[i - 1] if i % 2 == 0 else br[i] for i in range(len(br))]

    consensus_client.get_state_block_roots = Mock(side_effect=_get_state_block_roots)


def test_checkpoints_processor_get_block_roots(consensus_client, mock_get_state_block_roots, converter: Web3Converter):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        converter,
        state,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(0)
    assert len([r for r in roots if r is not None]) == 8192


def test_checkpoints_processor_get_block_roots_with_duplicates(
    consensus_client, mock_get_state_block_roots_with_duplicates, converter: Web3Converter
):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        converter,
        state,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(1)
    assert len([r for r in roots if r is not None]) == 4096


@pytest.fixture
def mock_get_config_spec(consensus_client):
    bc_spec = cast(BeaconSpecResponse, BeaconSpecResponseFactory.build())
    bc_spec.SLOTS_PER_HISTORICAL_ROOT = 8192
    consensus_client.get_config_spec = Mock(return_value=bc_spec)


def test_checkpoints_processor_select_block_roots(
    consensus_client, mock_get_state_block_roots, mock_get_config_spec, converter: Web3Converter
):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(0)
    selected = processor._select_block_roots(10, roots, 8192)
    assert len(selected) == 64
    assert selected == [f'0x{r}' for r in range(320, 384)]


def test_checkpoints_processor_select_block_roots_out_of_range(
    consensus_client, mock_get_state_block_roots, mock_get_config_spec, converter: Web3Converter
):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(0)
    with pytest.raises(ValueError, match="Slot is out of the state block roots range"):
        processor._select_block_roots(255, roots, 8192)


@pytest.fixture()
def mock_get_attestation_committees(consensus_client):
    def _get_attestation_committees(finalized_slot, epoch):
        committees = []
        validators = [v for v in range(0, 2048 * 32)]
        for i in range(epoch * 32, epoch * 32 + 32):  # 1 epoch = 32 slots.
            for j in range(0, 64):  # 64 committees per slot
                committee = deepcopy(cast(SlotAttestationCommittee, SlotAttestationCommitteeFactory.build()))
                committee.slot = i
                committee.index = j
                # 32 validators per committee
                committee.validators = [validators.pop() for _ in range(32)]
                committees.append(committee)
        return committees

    consensus_client.get_attestation_committees = Mock(side_effect=_get_attestation_committees)


def test_checkpoints_processor_prepare_committees(mock_get_attestation_committees, consensus_client, converter):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    raw = consensus_client.get_attestation_committees(0, 0)
    committees = processor._prepare_committees(0)
    assert len(committees) == 2048
    for index, (committee_id, validators) in enumerate(committees.items()):
        slot, committee_index = committee_id.split('_')
        committee_from_raw = raw[index]
        assert int(slot) == committee_from_raw.slot
        assert int(committee_index) == committee_from_raw.index
        assert len(validators) == 32
        for validator in validators:
            assert validator['included'] is False


def test_checkpoints_processor_process_attestations(mock_get_attestation_committees, consensus_client, converter):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    committees = processor._prepare_committees(0)
    # normal attestation
    attestation = cast(BlockAttestation, BlockAttestationFactory.build())
    attestation.data.slot = 0
    attestation.data.index = 0
    attestation.aggregation_bits = '0x' + 'f' * 32
    # the same but with no included attestations in bits
    attestation2 = cast(BlockAttestation, BlockAttestationFactory.build())
    attestation2.data.slot = 0
    attestation2.data.index = 0
    attestation2.aggregation_bits = '0x' + '0' * 32
    process_attestations([attestation, attestation2], committees)
    for validator in committees["0_0"]:
        # only the first attestation is accounted
        assert validator['included'] is True


def test_checkpoints_processor_process_attestations_undefined_committee(
    mock_get_attestation_committees, consensus_client, converter
):
    state = ...
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    committees = processor._prepare_committees(0)
    # undefined committee
    attestation = cast(BlockAttestation, BlockAttestationFactory.build())
    attestation.data.slot = 100500
    attestation.data.index = 100500
    attestation.aggregation_bits = '0x' + 'f' * 32
    process_attestations([attestation], committees)
    for validators in committees.values():
        for v in validators:
            assert v['included'] is False


@pytest.fixture()
def mock_get_block_attestations(consensus_client):
    def _get_block_attestations(root):
        attestations = []
        for i in range(0, 64):
            attestation = deepcopy(cast(BlockAttestation, BlockAttestationFactory.build()))
            attestation.data.slot = root[2:]
            attestation.data.index = str(i)
            attestation.aggregation_bits = '0x' + 'f' * 32
            attestations.append(attestation)
        return attestations

    consensus_client.get_block_attestations = Mock(side_effect=_get_block_attestations)


def test_checkpoints_processor_check_duty(
    mock_get_state_block_roots,
    mock_get_attestation_committees,
    mock_get_block_attestations,
    mock_get_config_spec,
    consensus_client,
    converter,
):
    state = State()
    state.validate_for_collect(0, 255)
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(0)
    processor._check_duty(0, roots[:64])
    assert len(state._processed_epochs) == 1
    assert len(state._epochs_to_process) == 256
    assert len(state.unprocessed_epochs) == 255
    assert len(state.data) == 2048 * 32


def test_checkpoints_processor_process(
    mock_get_state_block_roots,
    mock_get_attestation_committees,
    mock_get_block_attestations,
    mock_get_config_spec,
    consensus_client,
    converter,
):
    state = State()
    state.validate_for_collect(0, 255)
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    roots = processor._get_block_roots(0)
    processor._process([0, 1], {0: roots[:64], 1: roots[32:96]})
    assert len(state._processed_epochs) == 2
    assert len(state._epochs_to_process) == 256
    assert len(state.unprocessed_epochs) == 254
    assert len(state.data) == 2048 * 32


def test_checkpoints_processor_exec(
    mock_get_state_block_roots,
    mock_get_attestation_committees,
    mock_get_block_attestations,
    mock_get_config_spec,
    consensus_client,
    converter,
):
    state = State()
    state.validate_for_collect(0, 255)
    finalized_blockstamp = ...
    processor = CheckpointProcessor(
        consensus_client,
        state,
        converter,
        finalized_blockstamp,
    )
    iterator = CheckpointsIterator(converter, 0, 1, 255)
    for checkpoint in iterator:
        processor.exec(checkpoint)
    assert len(state._processed_epochs) == 2
    assert len(state._epochs_to_process) == 256
    assert len(state.unprocessed_epochs) == 254
    assert len(state.data) == 2048 * 32
