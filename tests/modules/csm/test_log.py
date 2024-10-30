import json
import pytest

from src.modules.csm.log import FramePerfLog, AttestationsAccumulator
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

    logs = [log]

    encoded = FramePerfLog.encode(logs)

    for decoded in json.loads(encoded):
        assert decoded["operators"]["42"]["validators"]["41337"]["perf"]["assigned"] == 220
        assert decoded["operators"]["42"]["validators"]["41337"]["perf"]["included"] == 119
        assert decoded["operators"]["42"]["distributed"] == 17
        assert decoded["operators"]["0"]["distributed"] == 0

        assert decoded["blockstamp"]["block_hash"] == log.blockstamp.block_hash
        assert decoded["blockstamp"]["ref_slot"] == log.blockstamp.ref_slot

        assert decoded["threshold"] == log.threshold
        assert decoded["frame"] == list(log.frame)


def test_logs_encode():
    log_0 = FramePerfLog(ReferenceBlockStampFactory.build(), (EpochNumber(100), EpochNumber(500)))
    log_0.operators[NodeOperatorId(42)].validators["41337"].perf = AttestationsAccumulator(220, 119)
    log_0.operators[NodeOperatorId(42)].distributed = 17
    log_0.operators[NodeOperatorId(0)].distributed = 0

    log_1 = FramePerfLog(ReferenceBlockStampFactory.build(), (EpochNumber(500), EpochNumber(900)))
    log_1.operators[NodeOperatorId(5)].validators["1234"].perf = AttestationsAccumulator(400, 399)
    log_1.operators[NodeOperatorId(5)].distributed = 40
    log_1.operators[NodeOperatorId(18)].distributed = 0

    logs = [log_0, log_1]

    encoded = FramePerfLog.encode(logs)

    decoded = json.loads(encoded)

    assert len(decoded) == 2

    assert decoded[0]["operators"]["42"]["validators"]["41337"]["perf"]["assigned"] == 220
    assert decoded[0]["operators"]["42"]["validators"]["41337"]["perf"]["included"] == 119
    assert decoded[0]["operators"]["42"]["distributed"] == 17
    assert decoded[0]["operators"]["0"]["distributed"] == 0

    assert decoded[1]["operators"]["5"]["validators"]["1234"]["perf"]["assigned"] == 400
    assert decoded[1]["operators"]["5"]["validators"]["1234"]["perf"]["included"] == 399
    assert decoded[1]["operators"]["5"]["distributed"] == 40
    assert decoded[1]["operators"]["18"]["distributed"] == 0

    for i, log in enumerate(logs):
        assert decoded[i]["blockstamp"]["block_hash"] == log.blockstamp.block_hash
        assert decoded[i]["blockstamp"]["ref_slot"] == log.blockstamp.ref_slot

        assert decoded[i]["threshold"] == log.threshold
        assert decoded[i]["frame"] == list(log.frame)
        assert decoded[i]["distributable"] == log.distributable
