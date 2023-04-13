from src.constants import MAX_SEED_LOOKAHEAD
from src.typings import ReferenceBlockStamp


def compute_activation_exit_epoch(blockstamp: ReferenceBlockStamp):
    """
    Return the epoch during which validator activations and exits initiated in ``epoch`` take effect.

    Spec: https://github.com/LeastAuthority/eth2.0-specs/blob/dev/specs/phase0/beacon-chain.md#compute_activation_exit_epoch
    """
    return blockstamp.ref_epoch + 1 + MAX_SEED_LOOKAHEAD
