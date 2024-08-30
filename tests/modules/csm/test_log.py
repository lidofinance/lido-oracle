from src.modules.csm.log import FramePerfLog
from src.types import EpochNumber, NodeOperatorId


def test_fields_access():
    log = FramePerfLog((EpochNumber(100), EpochNumber(500)))
    log.operators[NodeOperatorId(42)].validators["100500"].slashed = True
    log.operators[NodeOperatorId(17)].stuck = True
