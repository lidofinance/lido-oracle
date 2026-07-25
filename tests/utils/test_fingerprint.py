import json
import logging

import pytest

from src.utils.fingerprint import (
    BUCKETS,
    bucket_of,
    digest_of,
    fingerprint,
    fingerprint_hex,
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
class TestLogFingerprint:
    def test_log_fingerprint__valid_items__emits_summary_then_buckets(self, caplog):
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        # Act
        log_fingerprint(logger, 'Used Lido keys', [_pubkey(1), _pubkey(2)], el_block_number=42)
        # Assert
        summary, buckets = [record.msg for record in caplog.records]
        assert summary['msg'] == 'Used Lido keys fingerprint.'
        assert summary['count'] == 2
        assert summary['el_block_number'] == 42
        assert buckets['msg'] == 'Used Lido keys buckets.'
        assert buckets['bucket_counts'] == {'0': 2}

    def test_log_fingerprint__buckets_disabled__emits_summary_only(self, caplog):
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        # Act
        log_fingerprint(logger, 'CL validators', [_pubkey(1)], buckets=False)
        # Assert
        assert [record.msg['msg'] for record in caplog.records] == ['CL validators fingerprint.']

    def test_log_fingerprint__mainnet_scale__both_lines_survive_the_docker_split(self, caplog):
        """Docker's json-file driver cuts a log message at 16 KB and leaves reassembly to
        the collector, so every line has to land under that on its own."""
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        # Act
        log_fingerprint(logger, 'Pending Lido validators', [_pubkey(i) for i in range(24_000)])
        # Assert
        assert max(len(json.dumps(record.msg)) for record in caplog.records) < 16 * 1024

    def test_log_fingerprint__two_members__buckets_localise_the_difference(self, caplog):
        """What two operators actually do: compare bucket digests, then exchange only the
        keys in the one bucket that differs."""
        # Arrange
        caplog.set_level(logging.INFO)
        logger = logging.getLogger('test')
        full = [_pubkey(i << 40) for i in range(BUCKETS)]  # one key per bucket
        stale = full[137]
        # Act
        log_fingerprint(logger, 'Pending Lido validators', full)
        log_fingerprint(logger, 'Pending Lido validators', [k for k in full if k != stale])
        left, right = [r.msg for r in caplog.records if 'buckets' in r.msg]
        # Assert
        differing = [i for i in left['buckets'] if left['buckets'][i] != right['buckets'].get(i)]
        assert differing == [str(bucket_of(stale))]

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
