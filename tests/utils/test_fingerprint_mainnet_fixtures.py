"""Golden-master digests over real mainnet responses, captured once and replayed offline.

Two members can only compare digests if their oracles encode identically. Nothing in the
unit tests would catch an encoding change that is self-consistent but different from the
previous release — every digest would simply move together. These fixtures pin the encoding
to real data captured at mainnet slot 14921600, so such a change has to be deliberate.

Captured with `scripts/fingerprint_e2e.py`. Both are slices, twice over: the values are the
*parsed* projections the oracle keeps (`BeaconStateView` of a 956 MB response, `LidoKey`
without `vetted`), and each list is truncated to its first 2000 entries. That is enough for
what this file tests — every field of every type is exercised, and the encoding is what is
being pinned, not the response. Whether two real providers agree is the e2e script's job.

Regenerating these is a breaking change for anyone comparing against a running release, so
update the expected digests only alongside a deliberate encoding change.
"""

import gzip
import json
import pathlib

import pytest

from src.providers.consensus.types import BeaconStateView
from src.providers.keys.types import LidoKey
from src.utils.fingerprint import digest_of


FIXTURES = pathlib.Path(__file__).parent / 'fixtures'

# Mainnet, slot 14921600, first 2000 entries of each list.
BEACON_STATE_DIGEST = '0x84e677f732a20ff156026040f068b83374acb2036a02998a9ca76072e2a44f5d'
USED_KEYS_DIGEST = '0xe7a0f2013983d1bebab74b7690b61ec36c6b60a54f737aaa40c617fd8131efeb'


def _load(name: str):
    with gzip.open(FIXTURES / name, 'rt') as fd:
        return json.load(fd)


@pytest.mark.unit
class TestMainnetFixtures:
    @pytest.fixture
    def state(self) -> BeaconStateView:
        return BeaconStateView.from_response(**_load('mainnet_beacon_state_slice.json.gz'))

    @pytest.fixture
    def used_keys(self) -> list[LidoKey]:
        return [LidoKey.from_response(**key) for key in _load('mainnet_kapi_used_keys_slice.json.gz')]

    def test_digest_of__mainnet_beacon_state__matches_pinned_digest(self, state):
        assert digest_of(state) == BEACON_STATE_DIGEST

    def test_digest_of__mainnet_used_keys__matches_pinned_digest(self, used_keys):
        assert digest_of(used_keys) == USED_KEYS_DIGEST

    def test_digest_of__mainnet_beacon_state_reparsed__is_stable(self, state):
        """Same bytes parsed twice must digest the same — no dependence on object identity,
        dict ordering or iteration order anywhere in the encoder."""
        other = BeaconStateView.from_response(**_load('mainnet_beacon_state_slice.json.gz'))
        assert digest_of(other) == digest_of(state)

    def test_digest_of__one_mainnet_validator_changed__digest_changes(self, state):
        # Arrange — downward, since this validator sits at its maximum effective balance
        # and `ValidatorState` rejects anything above it.
        raw = _load('mainnet_beacon_state_slice.json.gz')
        raw['validators'][1337]['effective_balance'] -= 10**9
        # Act
        mutated = BeaconStateView.from_response(**raw)
        # Assert
        assert digest_of(mutated) != digest_of(state)

    def test_digest_of__one_mainnet_deposit_dropped__digest_changes(self, state):
        # Arrange
        raw = _load('mainnet_beacon_state_slice.json.gz')
        del raw['pending_deposits'][42]
        # Act
        mutated = BeaconStateView.from_response(**raw)
        # Assert
        assert digest_of(mutated) != digest_of(state)

    def test_digest_of__one_mainnet_key_dropped__digest_changes(self, used_keys):
        """The 2026-07-25 shape: one member's Keys API is short exactly one key."""
        # Act
        short = [key for key in used_keys if key is not used_keys[999]]
        # Assert
        assert digest_of(short) != digest_of(used_keys)
