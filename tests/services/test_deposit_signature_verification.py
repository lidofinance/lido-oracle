from unittest.mock import patch

import blst
import pytest

from src.constants import DOMAIN_DEPOSIT_TYPE, ETH1_ADDRESS_WITHDRAWAL_PREFIX, GENESIS_FORK_VERSION
from src.services.deposit_signature_verification import (
    _POP_DST,
    DepositMessage,
    compute_domain,
    compute_fork_data_root,
    compute_signing_root,
    is_valid_deposit_signature,
)


# SSZ-valid byte constants (sizes match the ssz field types)
_PUBKEY = bytes(48)  # ssz.bytes48
_WC = bytes(32)  # ssz.bytes32
_AMOUNT = 32_000_000_000
_SIGNATURE = bytes(96)


# ---- compute_fork_data_root ----


@pytest.mark.unit
def test_compute_fork_data_root_returns_32_bytes():
    root = compute_fork_data_root(bytes(4), bytes(32))
    assert isinstance(root, bytes)
    assert len(root) == 32


@pytest.mark.unit
def test_compute_fork_data_root_is_deterministic():
    r1 = compute_fork_data_root(bytes(4), bytes(32))
    r2 = compute_fork_data_root(bytes(4), bytes(32))
    assert r1 == r2


@pytest.mark.unit
def test_compute_fork_data_root_differs_on_fork_version():
    r1 = compute_fork_data_root(b'\x00\x00\x00\x00', bytes(32))
    r2 = compute_fork_data_root(b'\x01\x00\x00\x00', bytes(32))
    assert r1 != r2


@pytest.mark.unit
def test_compute_fork_data_root_differs_on_genesis_validators_root():
    r1 = compute_fork_data_root(bytes(4), bytes(32))
    r2 = compute_fork_data_root(bytes(4), b'\x01' + bytes(31))
    assert r1 != r2


# ---- compute_domain ----


@pytest.mark.unit
def test_compute_domain_length():
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    assert len(domain) == 32


@pytest.mark.unit
def test_compute_domain_starts_with_domain_type():
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    assert domain[:4] == DOMAIN_DEPOSIT_TYPE


@pytest.mark.unit
def test_compute_domain_uses_genesis_fork_version_by_default():
    # Explicit default args must equal no-arg call
    domain_defaults = compute_domain(DOMAIN_DEPOSIT_TYPE)
    domain_explicit = compute_domain(DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION, bytes(32))
    assert domain_defaults == domain_explicit


@pytest.mark.unit
def test_compute_domain_differs_on_fork_version():
    d1 = compute_domain(DOMAIN_DEPOSIT_TYPE, b'\x00\x00\x00\x00')
    d2 = compute_domain(DOMAIN_DEPOSIT_TYPE, b'\x01\x00\x00\x00')
    assert d1 != d2


@pytest.mark.unit
def test_compute_domain_differs_on_genesis_validators_root():
    d1 = compute_domain(DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION, bytes(32))
    d2 = compute_domain(DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION, b'\x01' + bytes(31))
    assert d1 != d2


@pytest.mark.unit
def test_compute_domain_differs_on_domain_type():
    d1 = compute_domain(b'\x03\x00\x00\x00')
    d2 = compute_domain(b'\x07\x00\x00\x00')
    assert d1 != d2


# ---- compute_signing_root ----


@pytest.mark.unit
def test_compute_signing_root_returns_32_bytes():
    msg = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=_WC, amount=_AMOUNT)
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    root = compute_signing_root(msg, domain)
    assert isinstance(root, bytes)
    assert len(root) == 32


@pytest.mark.unit
def test_compute_signing_root_is_deterministic():
    msg = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=_WC, amount=_AMOUNT)
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    assert compute_signing_root(msg, domain) == compute_signing_root(msg, domain)


@pytest.mark.unit
def test_compute_signing_root_differs_on_amount():
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    msg1 = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=_WC, amount=_AMOUNT)
    msg2 = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=_WC, amount=_AMOUNT + 1)
    assert compute_signing_root(msg1, domain) != compute_signing_root(msg2, domain)


@pytest.mark.unit
def test_compute_signing_root_differs_on_withdrawal_credentials():
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    msg1 = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=bytes(32), amount=_AMOUNT)
    msg2 = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=b'\x01' + bytes(31), amount=_AMOUNT)
    assert compute_signing_root(msg1, domain) != compute_signing_root(msg2, domain)


@pytest.mark.unit
def test_compute_signing_root_differs_on_domain():
    msg = DepositMessage(pubkey=_PUBKEY, withdrawal_credentials=_WC, amount=_AMOUNT)
    d1 = compute_domain(DOMAIN_DEPOSIT_TYPE, b'\x00\x00\x00\x00')
    d2 = compute_domain(DOMAIN_DEPOSIT_TYPE, b'\x01\x00\x00\x00')
    assert compute_signing_root(msg, d1) != compute_signing_root(msg, d2)


# ---- is_valid_deposit_signature ----
@pytest.mark.unit
def test_is_valid_deposit_signature_returns_true():
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.BLST_SUCCESS = 0
        mock_blst.P2_Affine.return_value.core_verify.return_value = 0
        result = is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)
    assert result is True


@pytest.mark.unit
def test_is_valid_deposit_signature_returns_false():
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.BLST_SUCCESS = 0
        mock_blst.P2_Affine.return_value.core_verify.return_value = 1
        result = is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)
    assert result is False


@pytest.mark.unit
def test_is_valid_deposit_signature_passes_correct_pubkey_and_signature():
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.BLST_SUCCESS = 0
        mock_blst.P2_Affine.return_value.core_verify.return_value = 0
        is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)

    (pubkey_arg,) = mock_blst.P1_Affine.call_args[0]
    (sig_arg,) = mock_blst.P2_Affine.call_args[0]
    assert pubkey_arg == _PUBKEY
    assert sig_arg == _SIGNATURE

    pk_arg, hash_or_encode_arg, signing_root_arg, dst_arg = mock_blst.P2_Affine.return_value.core_verify.call_args[0]
    assert pk_arg is mock_blst.P1_Affine.return_value
    assert hash_or_encode_arg is True
    assert isinstance(signing_root_arg, bytes)
    assert len(signing_root_arg) == 32
    assert dst_arg == _POP_DST


@pytest.mark.unit
def test_is_valid_deposit_signature_with_explicit_genesis_fork_version():
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.BLST_SUCCESS = 0
        mock_blst.P2_Affine.return_value.core_verify.return_value = 0
        result = is_valid_deposit_signature(
            _PUBKEY,
            _WC,
            _AMOUNT,
            _SIGNATURE,
            genesis_fork_version=b'\x01\x00\x00\x00',
        )
    assert result is True


@pytest.mark.unit
def test_is_valid_deposit_signature_with_explicit_genesis_validators_root():
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.BLST_SUCCESS = 0
        mock_blst.P2_Affine.return_value.core_verify.return_value = 0
        result = is_valid_deposit_signature(
            _PUBKEY,
            _WC,
            _AMOUNT,
            _SIGNATURE,
            genesis_validators_root=b'\xab' * 32,
        )
    assert result is True


@pytest.mark.unit
def test_is_valid_deposit_signature_different_fork_versions_produce_different_signing_roots():
    # Two calls with different fork versions must produce different signing roots
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.BLST_SUCCESS = 0
        mock_blst.P2_Affine.return_value.core_verify.return_value = 0

        is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE, genesis_fork_version=b'\x00\x00\x00\x00')
        root1 = mock_blst.P2_Affine.return_value.core_verify.call_args[0][2]

        is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE, genesis_fork_version=b'\x01\x00\x00\x00')
        root2 = mock_blst.P2_Affine.return_value.core_verify.call_args[0][2]

    assert root1 != root2


@pytest.mark.unit
def test_is_valid_deposit_signature_construction_error_returns_false():
    # Malformed/off-curve/off-subgroup points raise from this binding rather than returning
    # an error code - `is_valid_deposit_signature` must treat that as "invalid", not crash.
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.P1_Affine.side_effect = RuntimeError("1")
        result = is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)
    assert result is False


@pytest.mark.unit
def test_is_valid_deposit_signature_core_verify_raises_returns_false():
    # A verification mismatch can itself surface as a raised ValueError rather than a
    # non-success return code (observed behavior of this binding).
    with patch('src.services.deposit_signature_verification.blst') as mock_blst:
        mock_blst.P2_Affine.return_value.core_verify.side_effect = ValueError("BLST_ERROR: verify failed")
        result = is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)
    assert result is False


@pytest.mark.unit
class TestIsValidDepositSignatureRealCrypto:
    """Exercises the real blst binding with actual BLS12-381 keys, complementing
    the mocked plumbing tests above with genuine cryptographic verification."""

    def _sign(self, sk: int, pubkey: bytes, wc: bytes, amount: int, genesis_fork_version: bytes) -> bytes:
        deposit_message = DepositMessage(pubkey=pubkey, withdrawal_credentials=wc, amount=amount)
        domain = compute_domain(DOMAIN_DEPOSIT_TYPE, genesis_fork_version)
        signing_root = compute_signing_root(deposit_message, domain)

        secret_key = blst.SecretKey()
        secret_key.keygen(sk.to_bytes(32, 'big'))
        return blst.P2().hash_to(signing_root, _POP_DST).sign_with(secret_key).compress()

    def _pubkey(self, sk: int) -> bytes:
        secret_key = blst.SecretKey()
        secret_key.keygen(sk.to_bytes(32, 'big'))
        return blst.P1(secret_key).compress()

    def test_is_valid_deposit_signature__real_valid_deposit__returns_true(self):
        genesis_fork_version = b'\x10\x00\x00\x38'
        pubkey = self._pubkey(sk=12345)
        wc = ETH1_ADDRESS_WITHDRAWAL_PREFIX + '00' * 11 + 'aa' * 20
        wc_bytes = bytes.fromhex(wc[2:])
        amount = 32_000_000_000
        signature = self._sign(12345, pubkey, wc_bytes, amount, genesis_fork_version)

        result = is_valid_deposit_signature(
            pubkey, wc_bytes, amount, signature, genesis_fork_version=genesis_fork_version
        )

        assert result is True

    def test_is_valid_deposit_signature__tampered_amount__returns_false(self):
        genesis_fork_version = b'\x10\x00\x00\x38'
        pubkey = self._pubkey(sk=54321)
        wc = ETH1_ADDRESS_WITHDRAWAL_PREFIX + '00' * 11 + 'bb' * 20
        wc_bytes = bytes.fromhex(wc[2:])
        amount = 32_000_000_000
        signature = self._sign(54321, pubkey, wc_bytes, amount, genesis_fork_version)

        result = is_valid_deposit_signature(
            pubkey, wc_bytes, amount + 1, signature, genesis_fork_version=genesis_fork_version
        )

        assert result is False

    def test_is_valid_deposit_signature__garbage_pubkey__returns_false(self):
        result = is_valid_deposit_signature(bytes([0x11] * 48), bytes(32), 32_000_000_000, bytes([0x22] * 96))
        assert result is False

    def test_is_valid_deposit_signature__real_signature_from_mainnet__returns_true(self):
        result = is_valid_deposit_signature(
            b'\x80}\xfeG.\xc5`\xdb\x080-\xc2"\xa1\x86\xec\x89\x1e\xcf\x96\xec\xbd\xcf\xfec\xf33\x17\x1a\xa7KIV?\xfb\xddYFJAX)\x15a\x9d5\xfc\xd1',
            b'\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb9\xd7\x93Hx\xb5\xfb\x96\x10\xb3\xfe\x8a^D\x1e\x8f\xad~)?',
            32000000000,
            b"\xa1\xdd\x00\x02\x07\xb9\x9ca\xc2:KH\xebC;\xa1p\x0b7\x17\x05\xcaN\xa5\xc08\xd5\r\xe4G\xe4\xed\xf1\xaa\x96P\xcaN\xe2r\x99-\xb9\xb5\xb0[\x19\xa3\x05\\\x0c'\x11\x1bc\xee\x85\x16\xe6D\x0e\xaa\x9c!\xdd\xd2\xce\xf05x\x7f\xd28\x18e\xed\x94<\x9d\x01U'\x9am4\xdb\xfe\xe49\xf7t\xa2\x99\x04_\xcf",
            b'\x00\x00\x00\x00',
        )
        assert result is True

    def test_is_valid_deposit_signature__invalid_signature_from_mainnet__returns_false(self):
        result = is_valid_deposit_signature(
            b'\x80}\xfeG.\xc5`\xdb\x080-\xc2"\xa1\x86\xec\x88\x1e\xcf\x96\xec\xbd\xcf\xfec\xf33\x17\x1a\xa7KIV?\xfb\xddYFJAX)\x15a\x9d5\xfc\xd1',
            b'\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb9\xd7\x93Hx\xb5\xfb\x96\x10\xb3\xfe\x8a^D\x1e\x8f\xad~)?',
            32000000000,
            b"\xa1\xdd\x00\x02\x07\xb9\x9ca\xc2:KH\xebC;\xa1p\x0b7\x17\x05\xcaN\xa5\xc08\xd5\r\xe4G\xe4\xed\xf1\xaa\x96P\xcaN\xe2r\x99-\xb9\xb5\xb0[\x19\xa3\x05\\\x0c'\x11\x1bc\xee\x85\x16\xe6D\x0e\xaa\x9c!\xdd\xd2\xce\xf05x\x7f\xd28\x18e\xed\x94<\x9d\x01U'\x9am4\xdb\xfe\xe49\xf7t\xa2\x99\x04_\xcf",
            b'\x00\x00\x00\x00',
        )
        assert result is False

    def test_is_valid_deposit_signature__invalid_amount_from_mainnet__returns_false(self):
        result = is_valid_deposit_signature(
            b'\x80}\xfeG.\xc5`\xdb\x080-\xc2"\xa1\x86\xec\x89\x1e\xcf\x96\xec\xbd\xcf\xfec\xf33\x17\x1a\xa7KIV?\xfb\xddYFJAX)\x15a\x9d5\xfc\xd1',
            b'\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb9\xd7\x93Hx\xb5\xfb\x96\x10\xb3\xfe\x8a^D\x1e\x8f\xad~)?',
            33000000000,
            b"\xa1\xdd\x00\x02\x07\xb9\x9ca\xc2:KH\xebC;\xa1p\x0b7\x17\x05\xcaN\xa5\xc08\xd5\r\xe4G\xe4\xed\xf1\xaa\x96P\xcaN\xe2r\x99-\xb9\xb5\xb0[\x19\xa3\x05\\\x0c'\x11\x1bc\xee\x85\x16\xe6D\x0e\xaa\x9c!\xdd\xd2\xce\xf05x\x7f\xd28\x18e\xed\x94<\x9d\x01U'\x9am4\xdb\xfe\xe49\xf7t\xa2\x99\x04_\xcf",
            b'\x00\x00\x00\x00',
        )
        assert result is False
