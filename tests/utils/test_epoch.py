import pytest

from src.utils import epoch
from src.utils.epoch import compute_activation_exit_epoch
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.mark.unit
def test_compute_activation_exit_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as m:
        m.setattr(epoch, "MAX_SEED_LOOKAHEAD", 17)
        ref_blockstamp = ReferenceBlockStampFactory.build(ref_epoch=3546)
        result = compute_activation_exit_epoch(ref_blockstamp)
        assert result == 3546 + 17 + 1, "Unexpected activation exit epoch"
