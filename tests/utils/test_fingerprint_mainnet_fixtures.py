"""Golden-master digests over real mainnet responses, captured once and replayed offline.

Nothing else catches an encoding change that is self-consistent but differs from the previous
release, which would silently stop members on different versions from comparing. Repin only
alongside a deliberate encoding change. Captured from mainnet slot 14921600 with
`scripts/fingerprint_e2e.py`, each list truncated to its first 100 entries — small enough to
read in review, since a pin nobody can check against its input is a pin nobody can trust.
"""

import json
import pathlib

import pytest

from src.providers.consensus.types import BeaconStateView
from src.providers.keys.types import LidoKey
from src.utils.fingerprint import digest_of


FIXTURES = pathlib.Path(__file__).parent / 'fixtures'

# Mainnet, slot 14921600, first 100 entries of each list.
BEACON_STATE_DIGEST = '0x96af15ffc823a4ffdc5056e867c0c5c5d71f3ca09076e0ab5b0fe9b95040c862'
USED_KEYS_DIGEST = '0x8734ab5671c2e52f0854acf1cb234996dd75a8543eed82c220dfad051bf2843c'


def _load(name: str):
    with open(FIXTURES / name) as fd:
        return json.load(fd)


@pytest.mark.unit
class TestMainnetFixtures:
    @pytest.fixture
    def state(self) -> BeaconStateView:
        return BeaconStateView.from_response(**_load('mainnet_beacon_state_slice.json'))

    @pytest.fixture
    def used_keys(self) -> list[LidoKey]:
        return [LidoKey.from_response(**key) for key in _load('mainnet_kapi_used_keys_slice.json')]

    def test_digest_of__mainnet_beacon_state__matches_pinned_digest(self, state):
        assert digest_of(state) == BEACON_STATE_DIGEST

    def test_digest_of__mainnet_used_keys__matches_pinned_digest(self, used_keys):
        assert digest_of(used_keys) == USED_KEYS_DIGEST

    def test_digest_of__mainnet_beacon_state_reparsed__is_stable(self, state):
        """Same bytes parsed twice must digest the same — no dependence on object identity,
        dict ordering or iteration order anywhere in the encoder."""
        other = BeaconStateView.from_response(**_load('mainnet_beacon_state_slice.json'))
        assert digest_of(other) == digest_of(state)

    def test_digest_of__one_mainnet_validator_changed__digest_changes(self, state):
        # Arrange — downward, since this validator sits at its maximum effective balance
        # and `ValidatorState` rejects anything above it.
        raw = _load('mainnet_beacon_state_slice.json')
        raw['validators'][3]['effective_balance'] -= 10**9
        # Act
        mutated = BeaconStateView.from_response(**raw)
        # Assert
        assert digest_of(mutated) != digest_of(state)

    def test_digest_of__one_mainnet_deposit_dropped__digest_changes(self, state):
        # Arrange
        raw = _load('mainnet_beacon_state_slice.json')
        del raw['pending_deposits'][42]
        # Act
        mutated = BeaconStateView.from_response(**raw)
        # Assert
        assert digest_of(mutated) != digest_of(state)

    def test_digest_of__one_mainnet_key_dropped__digest_changes(self, used_keys):
        """The 2026-07-25 shape: one member's Keys API is short exactly one key."""
        # Act
        short = [key for key in used_keys if key is not used_keys[42]]
        # Assert
        assert digest_of(short) != digest_of(used_keys)
