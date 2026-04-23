from copy import deepcopy
from typing import cast
from unittest.mock import Mock, patch

import pytest

import modules.sidecars.performance.collector.checkpoint as checkpoint_module
from constants import EPOCHS_PER_SYNC_COMMITTEE_PERIOD, SLOTS_PER_HISTORICAL_ROOT
from modules.common.types import ChainConfig, FrameConfig
from modules.sidecars.performance.collector.checkpoint import (
    FrameCheckpoint,
    FrameCheckpointProcessor,
    FrameCheckpointsIterator,
    SlotNumber,
    SyncCommitteesCache,
    process_attestations,
)
from modules.sidecars.performance.common.db import DutiesDB
from modules.sidecars.performance.common.types import ProposalDuty, SyncDuty
from providers.consensus.client import ConsensusClient
from providers.consensus.types import BeaconSpecResponse, BlockAttestation, SlotAttestationCommittee, SyncCommittee
from tests.factory.bitarrays import BitListFactory
from tests.factory.configs import (
    BeaconSpecResponseFactory,
    BlockAttestationFactory,
    ChainConfigFactory,
    FrameConfigFactory,
    SlotAttestationCommitteeFactory,
)
from type_aliases import BlockRoot, EpochNumber, ValidatorIndex
from utils.web3converter import Web3Converter


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def no_db_write(monkeypatch):
    monkeypatch.setattr(DutiesDB, "store_epoch", Mock())


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
def consensus_client():
    return ConsensusClient(['http://localhost/'], 5 * 60)


@pytest.fixture
def processor(consensus_client: ConsensusClient, converter: Web3Converter):
    db = Mock()
    finalized_blockstamp = Mock(slot_number=SlotNumber(0))
    return FrameCheckpointProcessor(consensus_client, db, converter, finalized_blockstamp)


@pytest.fixture
def sync_committees_cache():
    with patch(
        'modules.sidecars.performance.collector.checkpoint.SYNC_COMMITTEES_CACHE', SyncCommitteesCache()
    ) as cache:
        yield cache


@pytest.fixture
def missing_slots() -> set[int]:
    return set()


@pytest.fixture
def mock_get_state_block_roots(consensus_client, missing_slots):
    def _get_state_block_roots(checkpoint_slot: int):
        roots = [checkpoint_module.ZERO_BLOCK_ROOT] * SLOTS_PER_HISTORICAL_ROOT
        for i in range(min(SLOTS_PER_HISTORICAL_ROOT, checkpoint_slot), 0, -1):
            slot = checkpoint_slot - i
            index = slot % SLOTS_PER_HISTORICAL_ROOT
            prev_slot_index = (slot - 1) % SLOTS_PER_HISTORICAL_ROOT
            roots[index] = roots[prev_slot_index] if slot in missing_slots else f"0x{slot}"

        oldest_slot = max(checkpoint_slot - SLOTS_PER_HISTORICAL_ROOT, 0)
        oldest_slot_index = oldest_slot % SLOTS_PER_HISTORICAL_ROOT
        roots[oldest_slot_index] = (
            f"0x{max(oldest_slot - 1, 0)}" if oldest_slot in missing_slots else f"0x{oldest_slot}"
        )
        return roots

    def _get_block_header(block_root: str):
        return Mock(data=Mock(header=Mock(message=Mock(slot=int(block_root.split('0x')[1])))))

    consensus_client.get_state_block_roots = Mock(side_effect=_get_state_block_roots)
    consensus_client.get_block_header = Mock(side_effect=_get_block_header)


@pytest.fixture
def mock_get_config_spec(consensus_client):
    bc_spec = cast(BeaconSpecResponse, BeaconSpecResponseFactory.build())
    bc_spec.SLOTS_PER_HISTORICAL_ROOT = SLOTS_PER_HISTORICAL_ROOT
    consensus_client.get_config_spec = Mock(return_value=bc_spec)


@pytest.fixture
def mock_get_attestation_committees(consensus_client):
    def _get_attestation_committees(_finalized_slot, epoch):
        committees = []
        validators = [ValidatorIndex(v) for v in range(0, 2048 * 32)]
        for slot in range(epoch * 32, epoch * 32 + 32):
            for committee_idx in range(0, 64):
                committee = deepcopy(cast(SlotAttestationCommittee, SlotAttestationCommitteeFactory.build()))
                committee.slot = SlotNumber(slot)
                committee.index = committee_idx
                committee.validators = [validators.pop() for _ in range(32)]
                committees.append(committee)
        return committees

    consensus_client.get_attestation_committees = Mock(side_effect=_get_attestation_committees)


def stub_db_metrics(db: Mock) -> None:
    db.has_epoch = lambda: False
    db.min_epoch = lambda: EpochNumber(8)
    db.max_epoch = lambda: EpochNumber(9)
    db.epochs_count = lambda: 2


def build_epoch_slots(duty_epoch: EpochNumber, slots_per_epoch: int) -> tuple[SlotNumber, SlotNumber, SlotNumber]:
    duty_epoch_first_slot = SlotNumber(int(duty_epoch) * slots_per_epoch)
    next_epoch_first_slot = SlotNumber(int(duty_epoch_first_slot) + slots_per_epoch)
    checkpoint_slot = SlotNumber(int(duty_epoch_first_slot) + 2 * slots_per_epoch)
    return duty_epoch_first_slot, next_epoch_first_slot, checkpoint_slot


def build_slot_roots(
    first_slot: SlotNumber,
    slots_per_epoch: int,
    present_slots: set[SlotNumber],
) -> list[tuple[SlotNumber, BlockRoot | None]]:
    return [
        (SlotNumber(slot), cast(BlockRoot, f"0x{slot}"))
        if SlotNumber(slot) in present_slots
        else (SlotNumber(slot), None)
        for slot in range(int(first_slot), int(first_slot) + slots_per_epoch)
    ]


def build_empty_epoch_slot_roots(
    first_slot: SlotNumber, slots_per_epoch: int
) -> list[tuple[SlotNumber, BlockRoot | None]]:
    return build_slot_roots(first_slot, slots_per_epoch, set())


def build_epoch_propose_duties(first_slot: SlotNumber, slots_per_epoch: int) -> dict[SlotNumber, ProposalDuty]:
    return {
        SlotNumber(slot): ProposalDuty(validator_index=slot, is_proposed=False)
        for slot in range(int(first_slot), int(first_slot) + slots_per_epoch)
    }


def mock_prev_slot_response(slot: SlotNumber) -> Mock:
    response = Mock()
    response.message.slot = slot
    return response


class TestFrameCheckpointsIterator:
    @pytest.mark.parametrize(
        "l_epoch,r_epoch,finalized_epoch,expected_checkpoints",
        [
            (0, 254, 253, [FrameCheckpoint(253 * 32, tuple(range(0, 252)))]),
            (0, 254, 254, [FrameCheckpoint(254 * 32, tuple(range(0, 253)))]),
            (0, 254, 255, [FrameCheckpoint(255 * 32, tuple(range(0, 254)))]),
            (
                0,
                254,
                256,
                [FrameCheckpoint(256 * 32, tuple(range(0, 255)))],
            ),
            (
                15,
                254,
                256,
                [FrameCheckpoint(256 * 32, tuple(range(15, 255)))],
            ),
            (
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
    def test_checkpoints_iterator_given_checkpoints(
        self, converter, l_epoch, r_epoch, finalized_epoch, expected_checkpoints
    ):
        iterator = FrameCheckpointsIterator(converter, l_epoch, r_epoch, finalized_epoch)
        assert list(iter(iterator)) == expected_checkpoints


class TestMetricsRefresh:
    def test_maybe_refresh_db_metrics_throttles_by_interval(self, processor: FrameCheckpointProcessor):
        processor._refresh_db_metrics = Mock()

        with patch.object(checkpoint_module.time, 'monotonic', side_effect=[100.0, 110.0, 131.0]):
            processor._maybe_refresh_db_metrics(interval_seconds=30.0)
            processor._maybe_refresh_db_metrics(interval_seconds=30.0)
            processor._maybe_refresh_db_metrics(interval_seconds=30.0)

        assert processor._refresh_db_metrics.call_count == 2
        assert processor._last_metrics_refresh == 131.0

    def test_exec_refreshes_metrics_via_maybe_refresh(self, processor: FrameCheckpointProcessor):
        processor._maybe_refresh_db_metrics = Mock()
        processor.db.has_epoch = Mock(return_value=True)

        processed = processor.exec(FrameCheckpoint(slot=SlotNumber(100), duty_epochs=[EpochNumber(10)]))

        assert processed == 0
        processor._maybe_refresh_db_metrics.assert_called_once_with(interval_seconds=0.0)


class TestBlockRoots:
    @pytest.mark.parametrize(
        "checkpoint_slot, missing_slots, expected_existing_roots_count",
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
        self,
        mock_get_state_block_roots,
        processor: FrameCheckpointProcessor,
        checkpoint_slot,
        expected_existing_roots_count,
    ):
        roots = processor._get_block_roots(checkpoint_slot)
        assert len([r for r in roots if r is not None]) == expected_existing_roots_count

    def test_checkpoints_processor_get_block_roots_pivot_zero_root(self, processor: FrameCheckpointProcessor):
        def _get_state_block_roots(_checkpoint_slot: int):
            return [checkpoint_module.ZERO_BLOCK_ROOT] * SLOTS_PER_HISTORICAL_ROOT

        processor.cc.get_state_block_roots = Mock(side_effect=_get_state_block_roots)
        processor.cc.get_block_header = Mock(side_effect=AssertionError("should not be called"))

        roots = processor._get_block_roots(1)

        assert all(r is None for r in roots)
        processor.cc.get_block_header.assert_not_called()

    def test_checkpoints_processor_select_block_roots(
        self,
        mock_get_state_block_roots,
        mock_get_config_spec,
        processor: FrameCheckpointProcessor,
    ):
        roots = processor._get_block_roots(8192)
        selected = processor._select_block_roots(roots, 10, 8192)
        duty_epoch_roots, next_epoch_roots = selected

        assert len(duty_epoch_roots) == 32
        assert len(next_epoch_roots) == 32
        assert duty_epoch_roots == [(r, f'0x{r}') for r in range(320, 352)]
        assert next_epoch_roots == [(r, f'0x{r}') for r in range(352, 384)]

    def test_checkpoints_processor_select_block_roots_out_of_range(
        self,
        mock_get_state_block_roots,
        mock_get_config_spec,
        processor: FrameCheckpointProcessor,
    ):
        roots = processor._get_block_roots(8192)
        with pytest.raises(checkpoint_module.SlotOutOfRootsRange, match="Slot is out of the state block roots range"):
            processor._select_block_roots(roots, 255, 8192)


class TestAttestations:
    def test_checkpoints_processor_prepare_committees(
        self, mock_get_attestation_committees, processor: FrameCheckpointProcessor
    ):
        raw = processor.cc.get_attestation_committees(processor.finalized_blockstamp, 0)
        committees, misses = processor._prepare_attestation_duties(0)

        assert len(committees) == 2048
        for index, (committee_id, validators) in enumerate(committees.items()):
            slot, committee_index = committee_id
            committee_from_raw = raw[index]
            assert slot == committee_from_raw.slot
            assert committee_index == committee_from_raw.index
            assert len(validators) == 32
            assert all(isinstance(v, int) for v in validators)
        assert len(misses) == 65536

    def test_checkpoints_processor_process_attestations(
        self, mock_get_attestation_committees, processor: FrameCheckpointProcessor
    ):
        attestation = cast(BlockAttestation, BlockAttestationFactory.build())
        attestation.data.slot = 0
        attestation.data.index = 0
        attestation.aggregation_bits = BitListFactory.build(set_indices=[i for i in range(32)]).hex()

        attestation2 = cast(BlockAttestation, BlockAttestationFactory.build())
        attestation2.data.slot = 0
        attestation2.data.index = 0
        attestation2.aggregation_bits = BitListFactory.build(set_indices=[]).hex()

        committees, misses = processor._prepare_attestation_duties(0)
        original_misses_count = len(misses)

        updated_misses = process_attestations([attestation, attestation2], committees, misses)

        assert len(updated_misses) == original_misses_count - 32

    def test_checkpoints_processor_process_attestations_undefined_committee(
        self,
        mock_get_attestation_committees,
        processor: FrameCheckpointProcessor,
    ):
        attestation = cast(BlockAttestation, BlockAttestationFactory.build())
        attestation.data.slot = 100500
        attestation.data.index = 100500
        attestation.aggregation_bits = '0x' + 'f' * 32

        committees, misses = processor._prepare_attestation_duties(0)
        original_misses = misses.copy()

        updated_misses = process_attestations([attestation], committees, misses)

        assert updated_misses == original_misses


class TestCheckDuties:
    def test_check_duties__epoch_has_attestations_and_sync_data__marks_proposals_and_stores(
        self,
        processor: FrameCheckpointProcessor,
    ):
        slots_per_epoch = processor.converter.chain_config.slots_per_epoch
        duty_epoch = EpochNumber(10)
        duty_epoch_first_slot, next_epoch_first_slot, checkpoint_slot = build_epoch_slots(duty_epoch, slots_per_epoch)

        checkpoint_block_roots = [None] * SLOTS_PER_HISTORICAL_ROOT
        duty_present_slots = {
            duty_epoch_first_slot,
            SlotNumber(int(duty_epoch_first_slot) + 1),
        }
        next_present_slots = {
            next_epoch_first_slot,
            SlotNumber(int(next_epoch_first_slot) + 1),
        }
        duty_epoch_roots = build_slot_roots(duty_epoch_first_slot, slots_per_epoch, duty_present_slots)
        next_epoch_roots = build_slot_roots(next_epoch_first_slot, slots_per_epoch, next_present_slots)

        expected_propose_duties = build_epoch_propose_duties(duty_epoch_first_slot, slots_per_epoch)
        processor._prepare_attestation_duties = Mock(return_value=({}, {1, 2}))
        processor._prepare_propose_duties = Mock(return_value=expected_propose_duties.copy())
        processor._prepare_sync_committee_duties = Mock(return_value=[SyncDuty(validator_index=1, missed_count=2)])

        attestation = Mock()
        attestation.data.slot = duty_epoch_first_slot
        attestation.data.index = 0
        attestation.aggregation_bits = "0xff"
        attestation.committee_bits = "0xff"

        sync_aggregate = Mock()
        sync_aggregate.sync_committee_bits = "0xff"

        processor.cc.get_block_attestations_and_sync = Mock(return_value=([attestation], sync_aggregate))
        stub_db_metrics(processor.db)

        processor._check_duties(
            checkpoint_block_roots,
            checkpoint_slot,
            duty_epoch,
            duty_epoch_roots,
            next_epoch_roots,
        )

        non_missing_roots_count = len(duty_present_slots) + len(next_present_slots)
        assert processor.cc.get_block_attestations_and_sync.call_count == non_missing_roots_count
        processor.db.store_epoch.assert_called_once()

        _, kwargs = processor.db.store_epoch.call_args
        proposals_by_slot = {
            slot: duty for slot, duty in zip(expected_propose_duties, kwargs["proposals"], strict=True)
        }
        assert proposals_by_slot[duty_epoch_first_slot].is_proposed
        assert proposals_by_slot[SlotNumber(int(duty_epoch_first_slot) + 1)].is_proposed
        assert not proposals_by_slot[SlotNumber(int(duty_epoch_first_slot) + 2)].is_proposed

    def test_check_duties__epoch_has_no_attestations__stores_epoch(self, processor: FrameCheckpointProcessor):
        slots_per_epoch = processor.converter.chain_config.slots_per_epoch
        duty_epoch = EpochNumber(10)
        duty_epoch_first_slot, next_epoch_first_slot, checkpoint_slot = build_epoch_slots(duty_epoch, slots_per_epoch)

        checkpoint_block_roots = [None] * SLOTS_PER_HISTORICAL_ROOT
        duty_epoch_roots = build_slot_roots(duty_epoch_first_slot, slots_per_epoch, {duty_epoch_first_slot})
        next_epoch_roots = build_slot_roots(next_epoch_first_slot, slots_per_epoch, {next_epoch_first_slot})

        processor._prepare_attestation_duties = Mock(return_value=({}, set()))
        processor._prepare_propose_duties = Mock(
            return_value=build_epoch_propose_duties(duty_epoch_first_slot, slots_per_epoch)
        )
        processor._prepare_sync_committee_duties = Mock(
            return_value=[SyncDuty(validator_index=i, missed_count=0) for i in range(0, 8)]
        )

        sync_aggregate = Mock()
        sync_aggregate.sync_committee_bits = "0x00"

        processor.cc.get_block_attestations_and_sync = Mock(return_value=([], sync_aggregate))
        stub_db_metrics(processor.db)

        processor._check_duties(
            checkpoint_block_roots,
            checkpoint_slot,
            duty_epoch,
            duty_epoch_roots,
            next_epoch_roots,
        )

        processor.db.store_epoch.assert_called_once()

    def test_check_duties__all_epoch_roots_missing__stores_epoch_without_block_requests(
        self,
        processor: FrameCheckpointProcessor,
    ):
        slots_per_epoch = processor.converter.chain_config.slots_per_epoch
        duty_epoch = EpochNumber(10)
        duty_epoch_first_slot, next_epoch_first_slot, checkpoint_slot = build_epoch_slots(duty_epoch, slots_per_epoch)

        checkpoint_block_roots = [None] * SLOTS_PER_HISTORICAL_ROOT
        duty_epoch_roots = build_empty_epoch_slot_roots(duty_epoch_first_slot, slots_per_epoch)
        next_epoch_roots = build_empty_epoch_slot_roots(next_epoch_first_slot, slots_per_epoch)

        expected_att_misses = {1, 2, 3}
        expected_sync_duties = [
            SyncDuty(validator_index=1, missed_count=0),
            SyncDuty(validator_index=2, missed_count=0),
        ]
        expected_propose_duties = {
            SlotNumber(slot): ProposalDuty(validator_index=slot, is_proposed=False)
            for slot in range(int(duty_epoch_first_slot), int(duty_epoch_first_slot) + slots_per_epoch)
        }
        processor._prepare_attestation_duties = Mock(return_value=({}, expected_att_misses.copy()))
        processor._prepare_propose_duties = Mock(return_value=expected_propose_duties.copy())
        processor._prepare_sync_committee_duties = Mock(return_value=expected_sync_duties.copy())
        processor.cc.get_block_attestations_and_sync = Mock()
        stub_db_metrics(processor.db)

        processor._check_duties(
            checkpoint_block_roots,
            checkpoint_slot,
            duty_epoch,
            duty_epoch_roots,
            next_epoch_roots,
        )

        processor.cc.get_block_attestations_and_sync.assert_not_called()
        processor.db.store_epoch.assert_called_once()

        args, kwargs = processor.db.store_epoch.call_args
        assert args[0] == duty_epoch
        assert kwargs["att_misses"] == expected_att_misses
        assert kwargs["syncs"] == expected_sync_duties
        assert len(kwargs["proposals"]) == slots_per_epoch
        assert all(not duty.is_proposed for duty in kwargs["proposals"])


class TestSyncCommittee:
    def test_prepare_sync_committee_returns_duties_for_valid_sync_committee(self, processor: FrameCheckpointProcessor):
        epoch = EpochNumber(10)
        sync_committee = Mock(spec=SyncCommittee)
        sync_committee.validators = [1, 2, 3]
        processor._get_sync_committee = Mock(return_value=sync_committee)

        duties = processor._prepare_sync_committee_duties(epoch)

        expected_duties = [
            SyncDuty(validator_index=1, missed_count=0),
            SyncDuty(validator_index=2, missed_count=0),
            SyncDuty(validator_index=3, missed_count=0),
        ]
        assert duties == expected_duties

    def test_get_sync_committee_returns_cached_sync_committee(
        self,
        processor: FrameCheckpointProcessor,
        sync_committees_cache: SyncCommitteesCache,
    ):
        epoch = EpochNumber(10)
        sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        cached_sync_committee = Mock(spec=SyncCommittee)
        sync_committees_cache[sync_committee_period] = cached_sync_committee

        result = processor._get_sync_committee(epoch)

        assert result == cached_sync_committee

    def test_get_sync_committee_fetches_and_caches_when_not_cached(
        self,
        processor: FrameCheckpointProcessor,
        sync_committees_cache: SyncCommitteesCache,
    ):
        epoch = EpochNumber(10)
        sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        sync_committee = Mock(spec=SyncCommittee)
        sync_committee.validators = [1, 2, 3]
        processor.converter.get_epoch_first_slot = Mock(return_value=SlotNumber(0))
        processor.cc.get_sync_committee = Mock(return_value=sync_committee)

        prev_slot_response = mock_prev_slot_response(SlotNumber(0))
        prev_slot_response.message.body.execution_payload.block_hash = "0x00"

        with patch(
            'modules.sidecars.performance.collector.checkpoint.get_prev_non_missed_slot',
            Mock(return_value=prev_slot_response),
        ):
            result = processor._get_sync_committee(epoch)

        assert result.validators == sync_committee.validators
        assert sync_committees_cache[sync_committee_period].validators == sync_committee.validators

    def test_get_sync_committee_handles_cache_eviction(
        self,
        processor: FrameCheckpointProcessor,
        sync_committees_cache: SyncCommitteesCache,
    ):
        epoch = EpochNumber(10)
        sync_committee_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        old_sync_committee_period = sync_committee_period - 1
        old_sync_committee = Mock(spec=SyncCommittee)
        sync_committee = Mock(spec=SyncCommittee)
        processor.cc.get_sync_committee = Mock(return_value=sync_committee)

        sync_committees_cache.max_size = 1
        sync_committees_cache[old_sync_committee_period] = old_sync_committee

        prev_slot_response = mock_prev_slot_response(SlotNumber(0))
        prev_slot_response.message.body.execution_payload.block_hash = "0x00"

        with patch(
            'modules.sidecars.performance.collector.checkpoint.get_prev_non_missed_slot',
            Mock(return_value=prev_slot_response),
        ):
            result = processor._get_sync_committee(epoch)

        assert result == sync_committee
        assert sync_committee_period in sync_committees_cache
        assert old_sync_committee_period not in sync_committees_cache


class TestProposeDuties:
    def test_prepare_propose_duties(self, processor: FrameCheckpointProcessor):
        epoch = EpochNumber(10)
        checkpoint_block_roots = [Mock(spec=BlockRoot), None, Mock(spec=BlockRoot)]
        checkpoint_slot = SlotNumber(100)
        dependent_root = Mock(spec=BlockRoot)
        processor._get_dependent_root_for_proposer_duties = Mock(return_value=dependent_root)
        proposer_duty1 = Mock(slot=SlotNumber(101), validator_index=1)
        proposer_duty2 = Mock(slot=SlotNumber(102), validator_index=2)
        processor.cc.get_proposer_duties = Mock(return_value=[proposer_duty1, proposer_duty2])

        duties = processor._prepare_propose_duties(epoch, checkpoint_block_roots, checkpoint_slot)

        expected_duties = {
            SlotNumber(101): ProposalDuty(validator_index=1, is_proposed=False),
            SlotNumber(102): ProposalDuty(validator_index=2, is_proposed=False),
        }
        assert duties == expected_duties

    def test_prepare_propose_duties__state_roots_missing__uses_cl_fallback_root(
        self, processor: FrameCheckpointProcessor
    ):
        epoch = EpochNumber(10)
        checkpoint_slot = processor.converter.get_epoch_first_slot(EpochNumber(epoch + 2))
        checkpoint_block_roots = [None] * SLOTS_PER_HISTORICAL_ROOT
        dependent_slot = processor.converter.get_epoch_last_slot(EpochNumber(epoch - 1))
        assert dependent_slot == SlotNumber(int(processor.converter.get_epoch_first_slot(epoch) - 1))
        fallback_root = cast(BlockRoot, "0x" + "11" * 32)

        prev_slot_response = mock_prev_slot_response(dependent_slot)
        processor.cc.get_block_root = Mock(return_value=Mock(root=fallback_root))

        proposer_duty = Mock(slot=processor.converter.get_epoch_first_slot(epoch), validator_index=1)
        processor.cc.get_proposer_duties = Mock(return_value=[proposer_duty])

        with patch(
            "modules.sidecars.performance.collector.checkpoint.get_prev_non_missed_slot",
            Mock(return_value=prev_slot_response),
        ) as get_prev_non_missed_slot_mock:
            duties = processor._prepare_propose_duties(epoch, checkpoint_block_roots, checkpoint_slot)

        get_prev_non_missed_slot_mock.assert_called_once()
        processor.cc.get_block_root.assert_called_once_with(dependent_slot)
        processor.cc.get_proposer_duties.assert_called_once_with(epoch, fallback_root)

        expected_duties = {
            processor.converter.get_epoch_first_slot(epoch): ProposalDuty(validator_index=1, is_proposed=False),
        }
        assert duties == expected_duties

    def test_get_dependent_root_for_proposer_duties__state_has_root__returns_state_root(
        self,
        processor: FrameCheckpointProcessor,
    ):
        epoch = EpochNumber(10)
        checkpoint_slot = processor.converter.get_epoch_first_slot(EpochNumber(epoch + 2))
        checkpoint_block_roots = [None] * SLOTS_PER_HISTORICAL_ROOT
        dependent_slot = processor.converter.get_epoch_last_slot(EpochNumber(epoch - 1))
        expected_root = cast(BlockRoot, "0x" + "22" * 32)
        checkpoint_block_roots[dependent_slot % SLOTS_PER_HISTORICAL_ROOT] = expected_root

        dependent_root = processor._get_dependent_root_for_proposer_duties(
            epoch,
            checkpoint_block_roots,
            checkpoint_slot,
        )

        assert dependent_root == expected_root

    def test_get_dependent_root_for_proposer_duties__slot_out_of_range__uses_cl_fallback(
        self,
        processor: FrameCheckpointProcessor,
    ):
        epoch = EpochNumber(300)
        checkpoint_block_roots = [None] * SLOTS_PER_HISTORICAL_ROOT
        checkpoint_slot = SlotNumber(100)
        non_missed_slot = SlotNumber(98)
        fallback_root = cast(BlockRoot, "0x" + "33" * 32)

        prev_slot_response = mock_prev_slot_response(non_missed_slot)
        processor.cc.get_block_root = Mock(return_value=Mock(root=fallback_root))

        with patch(
            'modules.sidecars.performance.collector.checkpoint.get_prev_non_missed_slot',
            Mock(return_value=prev_slot_response),
        ):
            dependent_root = processor._get_dependent_root_for_proposer_duties(
                epoch,
                checkpoint_block_roots,
                checkpoint_slot,
            )

        processor.cc.get_block_root.assert_called_once_with(non_missed_slot)
        assert dependent_root == fallback_root
