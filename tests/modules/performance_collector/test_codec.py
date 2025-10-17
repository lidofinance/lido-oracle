import pytest

from src.modules.performance_collector.codec import (
    ProposalDuty,
    ProposalDutiesCodec,
    SyncDuty,
    SyncDutiesCodec,
    AttDutiesMissCodec,
    EpochBlobCodec,
)


def _proposals_to_tuples(items: list[ProposalDuty]) -> list[tuple[int, int]]:
    return [(int(i.validator_index), int(bool(i.is_proposed))) for i in items]


def _syncs_to_tuples(items: list[SyncDuty]) -> list[tuple[int, int]]:
    return [(int(i.validator_index), int(i.missed_count)) for i in items]


PROPOSALS_EXAMPLE: list[ProposalDuty] = [
    ProposalDuty(validator_index=1001, is_proposed=True),
    ProposalDuty(validator_index=1023, is_proposed=False),
    ProposalDuty(validator_index=1098, is_proposed=True),
    ProposalDuty(validator_index=1110, is_proposed=True),
    ProposalDuty(validator_index=1177, is_proposed=False),
    ProposalDuty(validator_index=1205, is_proposed=True),
    ProposalDuty(validator_index=1266, is_proposed=False),
    ProposalDuty(validator_index=1314, is_proposed=True),
    ProposalDuty(validator_index=1333, is_proposed=False),
    ProposalDuty(validator_index=1402, is_proposed=True),
    ProposalDuty(validator_index=1444, is_proposed=True),
    ProposalDuty(validator_index=1509, is_proposed=False),
    ProposalDuty(validator_index=1531, is_proposed=True),
    ProposalDuty(validator_index=1600, is_proposed=False),
    ProposalDuty(validator_index=1625, is_proposed=True),
    ProposalDuty(validator_index=1702, is_proposed=True),
    ProposalDuty(validator_index=1737, is_proposed=False),
    ProposalDuty(validator_index=1801, is_proposed=True),
    ProposalDuty(validator_index=1822, is_proposed=False),
    ProposalDuty(validator_index=1905, is_proposed=True),
    ProposalDuty(validator_index=1950, is_proposed=False),
    ProposalDuty(validator_index=2007, is_proposed=True),
    ProposalDuty(validator_index=2059, is_proposed=True),
    ProposalDuty(validator_index=2103, is_proposed=False),
    ProposalDuty(validator_index=2166, is_proposed=True),
    ProposalDuty(validator_index=2201, is_proposed=False),
    ProposalDuty(validator_index=2255, is_proposed=True),
    ProposalDuty(validator_index=2311, is_proposed=False),
    ProposalDuty(validator_index=2399, is_proposed=True),
    ProposalDuty(validator_index=2420, is_proposed=False),
    ProposalDuty(validator_index=2504, is_proposed=True),
    ProposalDuty(validator_index=2570, is_proposed=False),
]


SYNCS_EXAMPLE: list[SyncDuty] = [
    SyncDuty(validator_index=8000, missed_count=0),
    SyncDuty(validator_index=8001, missed_count=1),
    SyncDuty(validator_index=8002, missed_count=2),
    SyncDuty(validator_index=8003, missed_count=3),
    SyncDuty(validator_index=8004, missed_count=4),
    SyncDuty(validator_index=8005, missed_count=5),
    SyncDuty(validator_index=8006, missed_count=6),
    SyncDuty(validator_index=8007, missed_count=7),
    SyncDuty(validator_index=8008, missed_count=8),
    SyncDuty(validator_index=8009, missed_count=9),
    SyncDuty(validator_index=8010, missed_count=10),
    SyncDuty(validator_index=8011, missed_count=11),
    SyncDuty(validator_index=8012, missed_count=12),
    SyncDuty(validator_index=8013, missed_count=13),
    SyncDuty(validator_index=8014, missed_count=14),
    SyncDuty(validator_index=8015, missed_count=15),
    SyncDuty(validator_index=8016, missed_count=16),
    SyncDuty(validator_index=8017, missed_count=17),
    SyncDuty(validator_index=8018, missed_count=18),
    SyncDuty(validator_index=8019, missed_count=19),
    SyncDuty(validator_index=8020, missed_count=20),
    SyncDuty(validator_index=8021, missed_count=21),
    SyncDuty(validator_index=8022, missed_count=22),
    SyncDuty(validator_index=8023, missed_count=23),
    SyncDuty(validator_index=8024, missed_count=24),
    SyncDuty(validator_index=8025, missed_count=25),
    SyncDuty(validator_index=8026, missed_count=26),
    SyncDuty(validator_index=8027, missed_count=27),
    SyncDuty(validator_index=8028, missed_count=28),
    SyncDuty(validator_index=8029, missed_count=29),
    SyncDuty(validator_index=8030, missed_count=30),
    SyncDuty(validator_index=8031, missed_count=31),
    SyncDuty(validator_index=8032, missed_count=32),
    SyncDuty(validator_index=8033, missed_count=0),
    SyncDuty(validator_index=8034, missed_count=2),
    SyncDuty(validator_index=8035, missed_count=4),
    SyncDuty(validator_index=8036, missed_count=6),
    SyncDuty(validator_index=8037, missed_count=8),
    SyncDuty(validator_index=8038, missed_count=10),
    SyncDuty(validator_index=8039, missed_count=12),
    SyncDuty(validator_index=8040, missed_count=14),
    SyncDuty(validator_index=8041, missed_count=16),
    SyncDuty(validator_index=8042, missed_count=18),
    SyncDuty(validator_index=8043, missed_count=20),
    SyncDuty(validator_index=8044, missed_count=22),
    SyncDuty(validator_index=8045, missed_count=24),
    SyncDuty(validator_index=8046, missed_count=26),
    SyncDuty(validator_index=8047, missed_count=28),
    SyncDuty(validator_index=8048, missed_count=30),
    SyncDuty(validator_index=8049, missed_count=32),
    SyncDuty(validator_index=8050, missed_count=1),
    SyncDuty(validator_index=8051, missed_count=3),
    SyncDuty(validator_index=8052, missed_count=5),
    SyncDuty(validator_index=8053, missed_count=7),
    SyncDuty(validator_index=8054, missed_count=9),
    SyncDuty(validator_index=8055, missed_count=11),
    SyncDuty(validator_index=8056, missed_count=13),
    SyncDuty(validator_index=8057, missed_count=15),
    SyncDuty(validator_index=8058, missed_count=17),
    SyncDuty(validator_index=8059, missed_count=19),
    SyncDuty(validator_index=8060, missed_count=21),
    SyncDuty(validator_index=8061, missed_count=23),
    SyncDuty(validator_index=8062, missed_count=25),
    SyncDuty(validator_index=8063, missed_count=27),
]


ATT_MISSES_EXAMPLE: set[int] = {
    10, 17, 21, 28, 35, 41, 43, 49, 57, 60,
    66, 72, 75, 81, 86, 90, 97, 101, 108, 112,
    119, 123, 127, 130, 137, 141, 149, 152, 159, 162,
    170, 173, 177, 182, 189, 193, 197, 201, 206, 210,
    215, 219, 223, 228, 234, 239, 241, 246, 251, 257,
    260, 266, 270, 274, 279, 283, 288, 292, 297, 301,
    305, 309, 314, 318, 323, 327, 330, 336, 340, 345,
}


@pytest.mark.unit
def test_proposal_duties_codec_roundtrip():
    src = PROPOSALS_EXAMPLE

    blob = ProposalDutiesCodec.encode(src)
    dst = ProposalDutiesCodec.decode(blob)

    # The codec sorts on encode; compare as sorted tuples
    assert sorted(_proposals_to_tuples(dst)) == sorted(_proposals_to_tuples(src))


@pytest.mark.unit
def test_proposal_duties_codec_empty():
    with pytest.raises(ValueError):
        ProposalDutiesCodec.decode(ProposalDutiesCodec.encode([]))


@pytest.mark.unit
def test_sync_miss_duties_codec_roundtrip():
    src = SYNCS_EXAMPLE

    blob = SyncDutiesCodec.encode(src)
    dst = SyncDutiesCodec.decode(blob)

    assert sorted(_syncs_to_tuples(dst)) == sorted(_syncs_to_tuples(src))


@pytest.mark.unit
def test_sync_miss_duties_codec_empty():
    with pytest.raises(ValueError):
        SyncDutiesCodec.decode(SyncDutiesCodec.encode([]))


@pytest.mark.unit
def test_sync_miss_duties_codec_out_of_range():
    with pytest.raises(ValueError):
        SyncDutiesCodec.encode([SyncDuty(validator_index=1, missed_count=33)])


@pytest.mark.unit
def test_att_duties_miss_codec_roundtrip():
    src = ATT_MISSES_EXAMPLE
    blob = AttDutiesMissCodec.encode(src)
    dst = AttDutiesMissCodec.decode(blob)
    assert set(dst) == set(src)


@pytest.mark.unit
def test_att_duties_miss_codec_empty():
    AttDutiesMissCodec.decode(AttDutiesMissCodec.encode(set()))


@pytest.mark.unit
def test_epoch_blob_codec_roundtrip():
    att_misses = ATT_MISSES_EXAMPLE
    proposals = PROPOSALS_EXAMPLE
    syncs = SYNCS_EXAMPLE

    blob = EpochBlobCodec.encode(att_misses=att_misses, proposals=proposals, sync_misses=syncs)
    att_decoded, proposals_decoded, syncs_decoded = EpochBlobCodec.decode(blob)

    # att_decoded may be a set (non-empty) or BitMap; normalize to set
    from pyroaring import BitMap  # type: ignore
    if isinstance(att_decoded, BitMap):
        att_decoded = set(att_decoded)  # type: ignore

    assert set(att_decoded) == set(att_misses)
    assert sorted(_proposals_to_tuples(proposals_decoded)) == sorted(_proposals_to_tuples(proposals))
    assert sorted(_syncs_to_tuples(syncs_decoded)) == sorted(_syncs_to_tuples(syncs))


@pytest.mark.unit
def test_epoch_blob_codec_bad_version():
    att_misses = set()
    proposals = PROPOSALS_EXAMPLE
    syncs = SYNCS_EXAMPLE

    blob = EpochBlobCodec.encode(att_misses=att_misses, proposals=proposals, sync_misses=syncs)

    bad = bytes([255]) + blob[1:]
    with pytest.raises(ValueError):
        EpochBlobCodec.decode(bad)


@pytest.mark.unit
def test_epoch_blob_codec_short_header():
    with pytest.raises(ValueError):
        EpochBlobCodec.decode(b"\x01\x00")


@pytest.mark.unit
def test_epoch_blob_codec_truncated_payload():
    att_misses = set()
    proposals = PROPOSALS_EXAMPLE
    syncs = SYNCS_EXAMPLE

    blob = EpochBlobCodec.encode(att_misses=att_misses, proposals=proposals, sync_misses=syncs)
    bad_blob = blob[:-1]

    with pytest.raises(ValueError):
        EpochBlobCodec.decode(bad_blob)
