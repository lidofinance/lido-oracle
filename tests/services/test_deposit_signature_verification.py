from unittest.mock import patch

import pytest

from src.constants import DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION
from src.services.deposit_signature_verification import (
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
    with patch('src.services.deposit_signature_verification.BLSVerifier') as mock_bls:
        mock_bls.Verify.return_value = True
        result = is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)
    assert result is True


@pytest.mark.unit
def test_is_valid_deposit_signature_returns_false():
    with patch('src.services.deposit_signature_verification.BLSVerifier') as mock_bls:
        mock_bls.Verify.return_value = False
        result = is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)
    assert result is False


@pytest.mark.unit
def test_is_valid_deposit_signature_passes_correct_pubkey_and_signature():
    with patch('src.services.deposit_signature_verification.BLSVerifier') as mock_bls:
        mock_bls.Verify.return_value = True
        is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE)

    pubkey_arg, signing_root_arg, sig_arg = mock_bls.Verify.call_args[0]
    assert pubkey_arg == _PUBKEY
    assert sig_arg == _SIGNATURE
    assert isinstance(signing_root_arg, bytes)
    assert len(signing_root_arg) == 32


@pytest.mark.unit
def test_is_valid_deposit_signature_with_explicit_genesis_fork_version():
    with patch('src.services.deposit_signature_verification.BLSVerifier') as mock_bls:
        mock_bls.Verify.return_value = True
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
    with patch('src.services.deposit_signature_verification.BLSVerifier') as mock_bls:
        mock_bls.Verify.return_value = True
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
    with patch('src.services.deposit_signature_verification.BLSVerifier') as mock_bls:
        mock_bls.Verify.return_value = True

        is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE, genesis_fork_version=b'\x00\x00\x00\x00')
        root1 = mock_bls.Verify.call_args[0][1]

        is_valid_deposit_signature(_PUBKEY, _WC, _AMOUNT, _SIGNATURE, genesis_fork_version=b'\x01\x00\x00\x00')
        root2 = mock_bls.Verify.call_args[0][1]

    assert root1 != root2
