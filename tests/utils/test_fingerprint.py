import json
import logging

import pytest

from src.utils.fingerprint import (
    BUCKETS,
    bucket_of,
    digest_of,
    fingerprint,
    fingerprint_hex,
    iblt_diff,
    iblt_sketch,
    log_fingerprint,
    log_fingerprint_hex,
)


def _pubkey(seed: int) -> bytes:
    return seed.to_bytes(48, 'big')


def _hex(seed: int) -> str:
    return '0x' + _pubkey(seed).hex()


@pytest.mark.unit
class TestFingerprint:
    def test_fingerprint__same_set_different_order__same_result(self):
        # Arrange
        items = [_pubkey(i) for i in range(100)]
        # Act
        left = fingerprint(items)
        right = fingerprint(reversed(items))
        # Assert
        assert left == right

    def test_fingerprint__different_set__different_digest(self):
        assert fingerprint([_pubkey(1)]).digest != fingerprint([_pubkey(2)]).digest

    def test_fingerprint__empty__does_not_raise(self):
        # Arrange / Act
        result = fingerprint([])
        # Assert
        assert result.count == 0
        assert result.buckets == {}
        assert result.xor == '0x'

    def test_fingerprint__counts_every_item__count_matches(self):
        assert fingerprint(_pubkey(i) for i in range(1000)).count == 1000

    def test_xor__one_missing_item__xor_delta_is_that_item(self):
        """The property the whole diagnostic rests on: when two members' sets differ by a
        single key, xor-ing their two logged values reproduces that key exactly."""
        # Arrange
        full = [_pubkey(i) for i in range(500)]
        missing = full[123]
        short = [item for item in full if item != missing]
        # Act
        delta = int(fingerprint(full).xor, 16) ^ int(fingerprint(short).xor, 16)
        # Assert
        assert delta.to_bytes(48, 'big') == missing

    def test_xor__identical_sets__delta_is_zero(self):
        items = [_pubkey(i) for i in range(50)]
        assert int(fingerprint(items).xor, 16) ^ int(fingerprint(items).xor, 16) == 0

    def test_buckets__one_missing_item__only_its_bucket_differs(self):
        # Arrange
        full = [_pubkey(i << 40) for i in range(BUCKETS)]  # one item per bucket
        missing = full[7]
        short = [item for item in full if item != missing]
        # Act
        left, right = fingerprint(full), fingerprint(short)
        differing = [index for index in left.buckets if left.buckets[index] != right.buckets.get(index)]
        # Assert
        assert differing == [str(bucket_of(missing))]

    def test_bucket_counts__sum_equals_count(self):
        # Arrange
        result = fingerprint(_pubkey(i * 7919) for i in range(2000))
        # Assert
        assert sum(result.bucket_counts.values()) == result.count

    def test_summary__omits_buckets(self):
        assert set(fingerprint([_pubkey(1)]).summary) == {'count', 'digest', 'xor'}

    def test_fingerprint_hex__hex_strings__matches_bytes_input(self):
        assert fingerprint_hex(_hex(i) for i in range(10)) == fingerprint(_pubkey(i) for i in range(10))

    def test_digest_of__order_changes__digest_changes(self):
        """Unlike `fingerprint`, this one must see reordering — the deposit queue is
        processed in order, so the same deposits in a different order is a divergence."""
        assert digest_of([b'a', b'b']) != digest_of([b'b', b'a'])

    def test_digest_of__same_order__digest_matches(self):
        assert digest_of([b'a', b'b']) == digest_of([b'a', b'b'])


@pytest.mark.unit
class TestIblt:
    def test_iblt_diff__identical_sets__no_difference(self):
        # Arrange
        items = [_pubkey(i) for i in range(500)]
        # Act
        diff = iblt_diff(iblt_sketch(items), iblt_sketch(items))
        # Assert
        assert diff.total == 0
        assert diff.decoded is True

    def test_iblt_diff__one_missing_entry__names_it_and_the_side(self):
        # Arrange
        full = [_pubkey(i) for i in range(1000)]
        missing = full[42]
        # Act
        diff = iblt_diff(iblt_sketch(full), iblt_sketch([i for i in full if i != missing]))
        # Assert
        assert diff.only_in_left == [missing]
        assert diff.only_in_right == []
        assert diff.decoded is True

    def test_iblt_diff__entries_missing_from_both_sides__separates_them(self):
        """The case a bare xor cannot express at all: each side holds keys the other lacks."""
        # Arrange
        shared = [_pubkey(i) for i in range(2000)]
        left_only = [_pubkey(900_001 + i) for i in range(7)]
        right_only = [_pubkey(800_001 + i) for i in range(4)]
        # Act
        diff = iblt_diff(iblt_sketch(shared + left_only), iblt_sketch(shared + right_only))
        # Assert
        assert diff.only_in_left == sorted(left_only)
        assert diff.only_in_right == sorted(right_only)
        assert diff.decoded is True

    @pytest.mark.parametrize('differences', [2, 5, 20, 50, 100, 200])
    def test_iblt_diff__many_differences__recovers_all_of_them(self, differences):
        """The reason the sketch exists: xor alone stops working past a single entry."""
        # Arrange
        shared = [_pubkey(i) for i in range(5000)]
        extra = [_pubkey(1_000_001 + i) for i in range(differences)]
        # Act
        diff = iblt_diff(iblt_sketch(shared + extra), iblt_sketch(shared))
        # Assert
        assert diff.only_in_left == sorted(extra)
        assert diff.decoded is True

    def test_iblt_diff__difference_beyond_capacity__reports_not_decoded(self):
        """Past capacity an IBLT stops abruptly rather than degrading, so the caller must
        be told the answer is partial instead of reading it as complete."""
        # Arrange
        shared = [_pubkey(i) for i in range(1000)]
        extra = [_pubkey(1_000_001 + i) for i in range(600)]
        # Act
        diff = iblt_diff(iblt_sketch(shared + extra), iblt_sketch(shared))
        # Assert
        assert diff.decoded is False
        assert diff.total < len(extra)

    def test_iblt_diff__wider_entries__recovers_whole_records(self):
        # Arrange
        records = [(i.to_bytes(192, 'big')) for i in range(300)]
        missing = records[7]
        # Act
        diff = iblt_diff(iblt_sketch(records), iblt_sketch([r for r in records if r != missing]))
        # Assert
        assert diff.only_in_left == [missing]

    def test_iblt_diff__mismatched_shapes__raises(self):
        with pytest.raises(ValueError, match='shape mismatch'):
            iblt_diff(iblt_sketch([_pubkey(1)], cells=256), iblt_sketch([_pubkey(1)], cells=512))

    def test_iblt_sketch__same_set_different_order__identical_sketch(self):
        items = [_pubkey(i) for i in range(200)]
        assert iblt_sketch(items) == iblt_sketch(reversed(items))


@pytest.mark.unit
class TestLogFingerprint:
    def test_log_fingerprint__valid_items__emits_summary_then_sketch_parts(self, caplog):
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        # Act
        log_fingerprint(logger, 'Used Lido keys', [_pubkey(1), _pubkey(2)], el_block_number=42)
        # Assert
        summary, *sketch = [record.msg for record in caplog.records]
        assert summary['msg'] == 'Used Lido keys fingerprint.'
        assert summary['count'] == 2
        assert summary['el_block_number'] == 42
        assert all(part['msg'] == 'Used Lido keys sketch.' for part in sketch)
        assert [part['part'] for part in sketch] == list(range(1, len(sketch) + 1))
        assert all(part['parts'] == len(sketch) for part in sketch)
        assert sketch[0]['bucket_counts'] == {'0': 2}

    def test_log_fingerprint__sketch_parts__each_survives_the_docker_line_split(self, caplog):
        """Docker's json-file driver splits a log message at 16 KB and leaves reassembly to
        the collector. Parts must land under that on their own."""
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        # Act
        log_fingerprint(logger, 'Pending Lido validators', [_pubkey(i) for i in range(24_000)])
        # Assert
        assert max(len(json.dumps(record.msg)) for record in caplog.records) < 16 * 1024

    def test_log_fingerprint__two_members__reassembled_parts_recover_the_difference(self, caplog):
        """End to end over the log records themselves: what two operators would actually
        paste into `scripts/reconcile_fingerprints.py`."""

        # Arrange
        def reassemble(records):
            return '0x' + ''.join(r['iblt'] for r in sorted(records, key=lambda r: r['part']))

        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        full = [_pubkey(i) for i in range(1000)]
        stale = full[404]
        # Act
        log_fingerprint(logger, 'Used Lido keys', full)
        boundary = len(caplog.records)
        log_fingerprint(logger, 'Used Lido keys', [k for k in full if k != stale])
        parts = [r.msg for r in caplog.records if 'iblt' in r.msg]
        left = reassemble([r.msg for r in caplog.records[:boundary] if 'iblt' in r.msg])
        right = reassemble([r.msg for r in caplog.records[boundary:] if 'iblt' in r.msg])
        # Assert
        assert len(parts) > 2, 'expected the sketch to be chunked'
        diff = iblt_diff(left, right)
        assert diff.only_in_left == [stale]
        assert diff.only_in_right == []
        assert diff.decoded is True

    def test_log_fingerprint_hex__malformed_hex__warns_instead_of_raising(self, caplog):
        """A report must never fail over a diagnostic."""
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        # Act
        log_fingerprint_hex(logger, 'Used Lido keys', ['0xnothex'])
        # Assert
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].msg['msg'] == 'Used Lido keys fingerprint failed.'
