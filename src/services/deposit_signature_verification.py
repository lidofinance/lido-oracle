# pyright: reportPrivateImportUsage=false
import ssz
from eth_typing import Hash32
from py_ecc.bls import G2ProofOfPossession as BLSVerifier
from py_ecc.bls.g2_primitives import BLSPubkey, BLSSignature

from src.constants import DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION


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


def compute_domain(
    domain_type: bytes,
    fork_version: bytes | None = None,
    genesis_validators_root: bytes | None = None,
) -> bytes:
    """
    Return the domain for the ``domain_type`` and ``fork_version``.

    Source:
    https://github.com/ethereum/consensus-specs/blob/f0f41198d6a8d7ae709d7d36a61c1e97c235d8ec/specs/phase0/beacon-chain.md?plain=1#L934
    """
    if fork_version is None:
        fork_version = GENESIS_FORK_VERSION

    if genesis_validators_root is None:
        genesis_validators_root = bytes([0] * 32)  # all bytes zero by default

    fork_data_root = compute_fork_data_root(fork_version, genesis_validators_root)
    return domain_type + fork_data_root[:28]


def compute_fork_data_root(current_version: bytes, genesis_validators_root: bytes) -> Hash32:
    """
    Return the 32-byte fork data root for the ``current_version`` and ``genesis_validators_root``.
    This is used primarily in signature domains to avoid collisions across forks/chains.

    Source:
    https://github.com/ethereum/consensus-specs/blob/139ff2875783ccba26c34aa15acebbcfba5f6eae/specs/phase0/beacon-chain.md?plain=1#L915
    """
    return ssz.get_hash_tree_root(
        ForkData(
            current_version=current_version,
            genesis_validators_root=genesis_validators_root,
        )
    )


def compute_signing_root(ssz_object: DepositMessage, domain: bytes) -> Hash32:
    """
    Return the signing root for the corresponding signing data.

    Source:
    https://github.com/ethereum/consensus-specs/blob/139ff2875783ccba26c34aa15acebbcfba5f6eae/specs/phase0/beacon-chain.md?plain=1#L950
    """
    return ssz.get_hash_tree_root(
        SigningData(
            object_root=ssz.get_hash_tree_root(ssz_object),
            domain=domain,
        )
    )


def is_valid_deposit_signature(
    pubkey: bytes,
    withdrawal_credentials: bytes,
    amount: int,
    signature: bytes,
    genesis_fork_version: bytes | None = None,
    genesis_validators_root: bytes | None = None,
) -> bool:
    """
    Return **True** if the deposit proof-of-possession (BLS signature) is valid.

    Source:
    https://github.com/ethereum/consensus-specs/blob/139ff2875783ccba26c34aa15acebbcfba5f6eae/specs/electra/beacon-chain.md#new-is_valid_deposit_signature
    """
    deposit_message = DepositMessage(
        pubkey=pubkey,
        withdrawal_credentials=withdrawal_credentials,
        amount=amount,
    )
    domain = compute_domain(DOMAIN_DEPOSIT_TYPE, genesis_fork_version, genesis_validators_root)
    signing_root = compute_signing_root(deposit_message, domain)
    return BLSVerifier.Verify(BLSPubkey(pubkey), signing_root, BLSSignature(signature))
