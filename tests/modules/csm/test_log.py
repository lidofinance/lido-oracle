import json

import pytest

from src.modules.csm.log import FramePerfLog
from src.modules.csm.state import AttestationsAccumulator
from src.types import EpochNumber, NodeOperatorId, ReferenceBlockStamp
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def ref_blockstamp() -> ReferenceBlockStamp:
    return ReferenceBlockStampFactory.build()


@pytest.fixture()
def frame() -> tuple[EpochNumber, EpochNumber]:
    return (EpochNumber(100), EpochNumber(500))


@pytest.fixture()
def log(ref_blockstamp: ReferenceBlockStamp, frame: tuple[EpochNumber, EpochNumber]) -> FramePerfLog:
    return FramePerfLog(ref_blockstamp, frame)


def test_fields_access(log: FramePerfLog):
    log.operators[NodeOperatorId(42)].validators["100500"].slashed = True
    log.operators[NodeOperatorId(17)].stuck = True


def test_log_encode(log: FramePerfLog):
    # Fill in dynamic fields to make sure we have data in it to be encoded.
    log.operators[NodeOperatorId(42)].validators["41337"].perf = AttestationsAccumulator(220, 119)
    log.operators[NodeOperatorId(42)].distributed = 17
    log.operators[NodeOperatorId(0)].distributed = 0

    encoded = log.encode()
    decoded = json.loads(encoded)

    assert decoded["operators"]["42"]["validators"]["41337"]["perf"]["assigned"] == 220
    assert decoded["operators"]["42"]["validators"]["41337"]["perf"]["included"] == 119
    assert decoded["operators"]["42"]["distributed"] == 17
    assert decoded["operators"]["0"]["distributed"] == 0

    assert decoded["blockstamp"]["block_hash"] == log.blockstamp.block_hash
    assert decoded["blockstamp"]["ref_slot"] == log.blockstamp.ref_slot

    assert decoded["threshold"] == log.threshold
    assert decoded["frame"] == list(log.frame)
