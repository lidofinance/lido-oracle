import dataclasses
import json
import logging

import pytest

from src.providers.consensus.types import (
    BeaconStateView,
    PendingConsolidation,
    PendingDeposit,
    PendingPartialWithdrawal,
    ValidatorState,
)
from src.providers.keys.types import LidoKey
from src.utils.fingerprint import digest_of, log_fingerprint


def _pubkey(seed: int) -> str:
    return '0x' + seed.to_bytes(48, 'big').hex()


def _lido_key(seed: int) -> LidoKey:
    return LidoKey(
        index=seed,
        key=_pubkey(seed),
        deposit_signature='0x' + seed.to_bytes(96, 'big').hex(),
        operator_index=seed % 7,
        used=True,
        module_address='0x' + seed.to_bytes(20, 'big').hex(),
    )


def _validator_state(seed: int) -> ValidatorState:
    return ValidatorState(
        pubkey=_pubkey(seed),
        withdrawal_credentials='0x01' + '00' * 11 + seed.to_bytes(20, 'big').hex(),
        effective_balance=32 * 10**9,
        slashed=False,
        activation_eligibility_epoch=seed,
        activation_epoch=seed + 1,
        exit_epoch=2**64 - 1,
        withdrawable_epoch=2**64 - 1,
    )


def _pending_deposit(seed: int) -> PendingDeposit:
    return PendingDeposit(
        pubkey=_pubkey(seed),
        withdrawal_credentials='0x02' + '00' * 11 + seed.to_bytes(20, 'big').hex(),
        amount=32 * 10**9,
        signature='0x' + seed.to_bytes(96, 'big').hex(),
        slot=1_000 + seed,
    )


def _state(validators: int = 4, deposits: int = 3) -> BeaconStateView:
    return BeaconStateView(
        slot=14846399,
        validators=[_validator_state(i) for i in range(validators)],
        balances=[32 * 10**9 + i for i in range(validators)],
        slashings=[0, 7],
        pending_deposits=[_pending_deposit(i) for i in range(deposits)],
        pending_partial_withdrawals=[
            PendingPartialWithdrawal(validator_index=0, amount=10**9, withdrawable_epoch=8),
            PendingPartialWithdrawal(validator_index=1, amount=2 * 10**9, withdrawable_epoch=9),
        ],
        pending_consolidations=[
            PendingConsolidation(source_index=0, target_index=1),
            PendingConsolidation(source_index=2, target_index=3),
        ],
    )


def _mutated(value, field: dataclasses.Field):
    """A different-but-plausible value for `field`, so a digest that ignores it fails."""
    current = getattr(value, field.name)
    match current:
        case bool():
            replacement = not current
        case int():
            replacement = current + 1
        case str():
            replacement = current[:-1] + ('0' if current.endswith('1') else '1')
        case list():
            replacement = current[1:]
        case _:
            raise AssertionError(f'No mutation defined for {field.name}: {type(current).__name__}')
    return dataclasses.replace(value, **{field.name: replacement})


@pytest.mark.unit
class TestDigestOf:
    def test_digest_of__same_value__same_digest(self):
        assert digest_of(_state()) == digest_of(_state())

    @pytest.mark.parametrize('field', dataclasses.fields(BeaconStateView), ids=lambda f: f.name)
    def test_digest_of__any_beacon_state_field_changes__digest_changes(self, field):
        """Every field of the CL response is covered — that is what 'full difference' means.
        A field added later without being fingerprinted fails here."""
        # Arrange
        state = _state()
        # Act
        mutated = _mutated(state, field)
        # Assert
        assert digest_of(state) != digest_of(mutated)

    @pytest.mark.parametrize('field', dataclasses.fields(LidoKey), ids=lambda f: f.name)
    def test_digest_of__any_lido_key_field_changes__digest_changes(self, field):
        # Arrange
        keys = [_lido_key(1), _lido_key(2)]
        # Act
        mutated = [_mutated(keys[0], field), keys[1]]
        # Assert
        assert digest_of(keys, ordered=False) != digest_of(mutated, ordered=False)

    def test_digest_of__nested_validator_field_changes__digest_changes(self):
        # Arrange
        state = _state()
        # Act
        other = _state()
        other.validators[2] = dataclasses.replace(other.validators[2], slashed=True)
        # Assert
        assert digest_of(state) != digest_of(other)

    def test_digest_of__ordered_and_list_reordered__digest_changes(self):
        """The deposit queue is processed in order and the filter keeps the first deposit per
        pubkey, so the same deposits in a different order is a real divergence."""
        # Arrange
        state = _state()
        reordered = _state()
        reordered.pending_deposits.reverse()
        # Assert
        assert digest_of(state) != digest_of(reordered)

    def test_digest_of__unordered_and_list_reordered__digest_unchanged(self):
        """The Keys API promises no row order, so an order-sensitive digest would report two
        identical key sets as different."""
        # Arrange
        keys = [_lido_key(i) for i in range(10)]
        # Assert
        assert digest_of(keys, ordered=False) == digest_of(list(reversed(keys)), ordered=False)

    def test_digest_of__unordered_and_nested_list_reordered__digest_unchanged(self):
        # Arrange
        response = {'keys': [_lido_key(i) for i in range(5)], 'module': {'id': 1}}
        shuffled = {'module': {'id': 1}, 'keys': list(reversed(response['keys']))}
        # Assert
        assert digest_of(response, ordered=False) == digest_of(shuffled, ordered=False)

    def test_digest_of__unordered_and_entry_missing__digest_changes(self):
        # Arrange
        keys = [_lido_key(i) for i in range(10)]
        # Assert
        assert digest_of(keys, ordered=False) != digest_of(keys[1:], ordered=False)

    def test_digest_of__unordered_and_duplicate_entry__digest_changes(self):
        """Set semantics on the ordering only. A key served twice is a Keys API bug and must
        not hash the same as a key served once."""
        # Arrange
        keys = [_lido_key(1)]
        # Assert
        assert digest_of(keys, ordered=False) != digest_of(keys * 2, ordered=False)

    def test_digest_of__dict_key_order__digest_unchanged(self):
        assert digest_of({'a': 1, 'b': 2}) == digest_of({'b': 2, 'a': 1})

    @pytest.mark.parametrize(
        ('left', 'right'),
        [
            (['ab'], ['a', 'b']),
            ({'a': 'bc'}, {'ab': 'c'}),
            ([1, 23], [12, 3]),
            (['1'], [1]),
            ([[1], [2]], [[1, 2]]),
        ],
    )
    def test_digest_of__ambiguous_looking_values__digests_differ(self, left, right):
        """The encoding is self-delimiting: distinct values never collide by concatenation."""
        assert digest_of(left) != digest_of(right)

    def test_digest_of__unsupported_type__raises(self):
        with pytest.raises(TypeError, match='Cannot fingerprint'):
            digest_of({1.5})


@pytest.mark.unit
class TestLogFingerprint:
    @pytest.fixture
    def logger(self, caplog):
        caplog.set_level(logging.INFO)
        return logging.getLogger('test')

    def test_log_fingerprint__valid_value__emits_one_line_with_context(self, logger, caplog):
        # Act
        log_fingerprint(logger, 'Beacon state', _state(), state_root='0xabc')
        # Assert
        assert len(caplog.records) == 1
        line = caplog.records[0].msg
        assert line['msg'] == 'Beacon state fingerprint.'
        assert line['state_root'] == '0xabc'
        assert line['digest'].startswith('0x')

    def test_log_fingerprint__large_input__line_stays_small(self, logger, caplog):
        """One digest per response and nothing else, so the line can be shipped and grepped."""
        # Act
        log_fingerprint(logger, 'Keys API used keys', [_lido_key(i) for i in range(20_000)], ordered=False)
        # Assert
        assert len(json.dumps(caplog.records[0].msg)) < 256

    def test_log_fingerprint__differing_responses__digests_differ(self, logger, caplog):
        """What two operators actually do with one log line each."""
        # Act
        log_fingerprint(logger, 'Keys API used keys', [_lido_key(i) for i in range(100)], ordered=False)
        log_fingerprint(logger, 'Keys API used keys', [_lido_key(i) for i in range(100) if i != 42], ordered=False)
        # Assert
        left, right = (record.msg['digest'] for record in caplog.records)
        assert left != right

    def test_log_fingerprint__unfingerprintable_value__warns_instead_of_raising(self, logger, caplog):
        """A report must never fail over a diagnostic."""
        # Act
        log_fingerprint(logger, 'Beacon state', object())
        # Assert
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING
        assert caplog.records[0].msg['msg'] == 'Beacon state fingerprint failed.'
