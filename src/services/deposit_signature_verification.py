# pyright: reportPrivateImportUsage=false
from typing import Any

import blst
import ssz
from eth_typing import Hash32

from src.constants import DOMAIN_DEPOSIT_TYPE, GENESIS_FORK_VERSION


# Domain separation tag for the BLS "proof of possession" ciphersuite (min-pubkey-size,
# RFC 9380 SSWU random-oracle hash-to-curve) used by Ethereum deposits.
_POP_DST = b"BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_POP_"


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

    try:
        bls_pubkey = blst.P1_Affine(pubkey)
        bls_signature = blst.P2_Affine(signature)
        return bls_signature.core_verify(bls_pubkey, True, signing_root, _POP_DST) == blst.BLST_SUCCESS
    except (RuntimeError, ValueError):  # Invalid signature
        return False


# A real mainnet Lido deposit: Community Staking module, operator 1, key index 0, against
# the mainnet withdrawal vault. It must verify, and must stop verifying once perturbed.
_KAT_PUBKEY = '0x8625e651cdd6754903520e79eca7f534b53e4ef230a0fb57aeb1cf35395387174fbe76648445387cfb6bbb55e9294bc1'
_KAT_WITHDRAWAL_CREDENTIALS = '0x010000000000000000000000b9d7934878b5fb9610b3fe8a5e441e8fad7e293f'
_KAT_SIGNATURE = (
    '0xb783048aab91cd28d1a73552d9edc40c2df7bca233ce544ef323521db4763f36aed0077ac4c0f83e52618e38f196f0be'
    '03c94127d3a6a688eb69cf7ddd5efa71ef53178c1ddbb4115c2bb8382da92c88e4d43c6e7aa8503366e74dfe4b9ab229'
)
_KAT_AMOUNT = 32_000_000_000


def bls_selfcheck() -> dict[str, Any]:
    """Verify the BLS stack against a fixed vector and describe the result.

    A rejected deposit is one missing from the pending balance, and it leaves no trace in
    the chain data, so a backend disagreement is invisible after the fact. Reporting the
    signing root too separates an SSZ or domain difference from a curve library one.
    """
    pubkey = bytes.fromhex(_KAT_PUBKEY[2:])
    withdrawal_credentials = bytes.fromhex(_KAT_WITHDRAWAL_CREDENTIALS[2:])
    signature = bytes.fromhex(_KAT_SIGNATURE[2:])

    domain = compute_domain(DOMAIN_DEPOSIT_TYPE)
    signing_root = compute_signing_root(
        DepositMessage(pubkey=pubkey, withdrawal_credentials=withdrawal_credentials, amount=_KAT_AMOUNT),
        domain,
    )

    def verify(amount: int) -> bool:
        return is_valid_deposit_signature(
            pubkey=pubkey,
            withdrawal_credentials=withdrawal_credentials,
            amount=amount,
            signature=signature,
        )

    valid_accepted = verify(_KAT_AMOUNT)
    tampered_rejected = not verify(_KAT_AMOUNT + 1)

    return {
        'backend': getattr(blst, '__file__', None),
        'domain': '0x' + domain.hex(),
        'signing_root': '0x' + signing_root.hex(),
        'valid_accepted': valid_accepted,
        'tampered_rejected': tampered_rejected,
        'ok': valid_accepted and tampered_rejected,
    }
