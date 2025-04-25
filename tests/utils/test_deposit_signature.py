"""Test for utils.deposit_signature module"""

import pytest

from src.utils.deposit_signature import (
    compute_fork_data_root,
    compute_domain,
    is_valid_deposit_signature,
    GENESIS_FORK_VERSION,
    GENESIS_VALIDATORS_ROOT,
    DOMAIN_DEPOSIT_TYPE,
)
from src.utils.types import hex_str_to_bytes

HOODI_FORK_VERSION = "0x10000910"


@pytest.mark.parametrize(
    "fork_version, genesis_validators_root, expected",
    [
        (
            GENESIS_FORK_VERSION,
            GENESIS_VALIDATORS_ROOT,
            bytes.fromhex("f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a92759fb4b"),
        ),
        (
            HOODI_FORK_VERSION,
            GENESIS_VALIDATORS_ROOT,
            bytes.fromhex("719103511efa4f1362ff2a50996cccf329cc84cb410c5e5c7d351d0353d25e6c"),
        ),
    ],
)
def test_compute_fork_data_root(fork_version, genesis_validators_root, expected):
    fork_version_bytes = hex_str_to_bytes(fork_version)
    fork_data_root = compute_fork_data_root(fork_version_bytes, bytes(genesis_validators_root))

    print(fork_data_root.hex())
    assert isinstance(fork_data_root, bytes)
    assert len(fork_data_root) == 32  # Should be 32 bytes
    assert fork_data_root == expected


@pytest.mark.parametrize(
    "domain_type, fork_version, genesis_validators_root, expected",
    [
        (
            DOMAIN_DEPOSIT_TYPE,
            GENESIS_FORK_VERSION,
            GENESIS_VALIDATORS_ROOT,
            bytes.fromhex("03000000f5a5fd42d16a20302798ef6ed309979b43003d2320d9f0e8ea9831a9"),
        ),
        (
            DOMAIN_DEPOSIT_TYPE,
            HOODI_FORK_VERSION,
            GENESIS_VALIDATORS_ROOT,
            bytes.fromhex("03000000719103511efa4f1362ff2a50996cccf329cc84cb410c5e5c7d351d03"),
        ),
    ],
)
def test_compute_domain(domain_type, fork_version, genesis_validators_root, expected):
    domain = compute_domain(bytes(domain_type), bytes(fork_version), bytes(genesis_validators_root))

    print(domain.hex())
    assert len(domain) == 32  # Should be 32 bytes
    assert isinstance(domain, bytes)
    assert domain[:4] == domain_type  # First byte should be domain type
    assert domain == expected


@pytest.mark.parametrize(
    "pubkey, withdrawal_credentials, amount_gwei, signature, expected",
    [
        # This one uses fork_version 0x00000000 (not for Hoodi, thus should be False)
        (
            "a50a7821c793e80710f51c681b28f996e5c2f1fa00318dbf91b5844822d58ac2fef892b79aea386a3b97829e090a393e",
            "020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc",
            1000000000,
            "b5b222b452892bd62a7d2b4925e15bf9823c4443313d86d3e1fe549c86aa8919d0cdd1d5b60d9d3184f3966ced21699f124a14a0d8c1f1ae3e9f25715f40c3e7b81a909424c60ca7a8cbd79f101d6bd86ce1bdd39701cf93b2eecce10699f40b",
            False,
        ),
        # Those two are valid signatures for Hoodi
        (
            "8c96ad1b9a1acf4a898009d96293d191ab911b535cd1e6618e76897b5fa239a7078f1fbf9de8dd07a61a51b137c74a87",
            "020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc",
            1000000000,
            "978f286178050a3dbf6f8551b8020f72dd1de8223fc9cb8553d5ebb22f71164f4278d9b970467084a9dcd54ad07ec8d60792104ff82887b499346f3e8adc55a86f26bfbb032ac2524da42d5186c5a8ed0ccf9d98e9f6ff012cfafbd712335aa5",
            True,
        ),
        (
            "99eeb66e77fef5c71d3b303774ecded0d52d521e8d665c2d0f350c33f5f82e7ddd88dd9bc4f8014fb22820beda3a8a85",
            "020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc",
            1000000000,
            "b4ea337eb8d0fc47361672d4a153dbe3cd943a0418c9f1bc586bca95cdcf8615d60a2394b7680276c4597a2524f9bcf1088c40a08902841ff68d508a9f825803b9fac3bc6333cf3afa7503f560ccf6f689be5b0f5d08fa9e21cb203aa1f53259",
            True,
        ),
    ],
)
def test_is_valid_deposit_signature(pubkey, withdrawal_credentials, amount_gwei, signature, expected):
    result = is_valid_deposit_signature(
        pubkey=bytes.fromhex(pubkey),
        withdrawal_credentials=bytes.fromhex(withdrawal_credentials),
        amount_gwei=amount_gwei,
        signature=bytes.fromhex(signature),
        fork_version=HOODI_FORK_VERSION,
        genesis_validators_root=GENESIS_VALIDATORS_ROOT,
    )

    assert result == expected