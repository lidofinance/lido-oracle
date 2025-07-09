import ssz

from py_ecc.bls import G2ProofOfPossession as BLSVerifier
from py_ecc.bls.g2_primitives import BLSPubkey, BLSSignature

from src.utils.types import hex_str_to_bytes

GENESIS_VALIDATORS_ROOT = bytes([0] * 32)  # all zeros for deposits

# https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#domain-types
DOMAIN_DEPOSIT_TYPE = bytes.fromhex("03000000")  # 0x03000000


class DepositMessage(ssz.Serializable):
    fields = [
        ("pubkey", ssz.bytes48),
        ("withdrawal_credentials", ssz.bytes32),
        ("amount", ssz.uint64),  # value in Gwei
    ]


class ForkData(ssz.Serializable):
    fields = [
        ("current_version", ssz.bytes4),
        ("genesis_validators_root", ssz.bytes32),
    ]


class SigningData(ssz.Serializable):
    fields = [
        ("object_root", ssz.bytes32),
        ("domain", ssz.bytes32),
    ]


def compute_fork_data_root(
    fork_version: bytes,
    genesis_validators_root: bytes,
) -> bytes:
    """
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#compute_fork_data_root
    """
    return ssz.get_hash_tree_root(ForkData(fork_version, genesis_validators_root))


def compute_domain(
    domain_type: bytes,
    fork_version: bytes,
    genesis_validators_root: bytes,
) -> bytes:
    """
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#compute_domain
    """
    fork_data_root = compute_fork_data_root(fork_version, genesis_validators_root)
    return domain_type + fork_data_root[:28]


def compute_signing_root(
    message: DepositMessage,
    domain: bytes,
) -> bytes:
    """
    https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#compute_signing_root
    """
    object_root = ssz.get_hash_tree_root(message)
    return ssz.get_hash_tree_root(SigningData(object_root, domain))


def is_valid_deposit_signature(
    pubkey: bytes,
    withdrawal_credentials: bytes,
    amount_gwei: int,
    signature: bytes,
    fork_version: str,
    genesis_validators_root: bytes = GENESIS_VALIDATORS_ROOT,
) -> bool:
    """Return **True** if the deposit proof-of-possession (BLS signature) is valid.

    Parameters
    ----------
    pubkey : bytes
        48-byte BLS public key
    withdrawal_credentials : bytes
        32-byte field from the deposit data
    amount_gwei : int
        Integer value in **Gwei** (NOT wei)
    signature : bytes
        96-byte BLS signature
    fork_version : bytes
        4-byte fork version
    genesis_validators_root : bytes
        32-byte genesis validators root
    """

    fork_version_bytes = hex_str_to_bytes(fork_version)

    message = DepositMessage(pubkey, withdrawal_credentials, amount_gwei)
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE, fork_version_bytes, genesis_validators_root)
    signing_root = compute_signing_root(message, domain)

    return BLSVerifier.Verify(BLSPubkey(pubkey), signing_root, BLSSignature(signature))
