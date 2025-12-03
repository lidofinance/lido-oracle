import json
import pytest

from src.modules.csm.log import FramePerfLog, DutyAccumulator
from src.providers.execution.contracts.cs_parameters_registry import PerformanceCoefficients
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


@pytest.mark.unit
def test_fields_access(log: FramePerfLog):
    log.operators[NodeOperatorId(42)].validators["100500"].slashed = True


@pytest.mark.unit
def test_logs_encode(log: FramePerfLog):
    # Fill in dynamic fields to make sure we have data in it to be encoded.
    log.operators[NodeOperatorId(42)].distributed_rewards = 17
    log.operators[NodeOperatorId(42)].performance_coefficients = PerformanceCoefficients()
    log.operators[NodeOperatorId(42)].validators["41337"].attestation_duty = DutyAccumulator(220, 119)
    log.operators[NodeOperatorId(42)].validators["41337"].proposal_duty = DutyAccumulator(1, 1)
    log.operators[NodeOperatorId(42)].validators["41337"].sync_duty = DutyAccumulator(100500, 100000)
    log.operators[NodeOperatorId(42)].validators["41337"].performance = 0.5
    log.operators[NodeOperatorId(42)].validators["41337"].threshold = 0.7
    log.operators[NodeOperatorId(42)].validators["41337"].rewards_share = 0.3
    log.operators[NodeOperatorId(42)].validators["41337"].distributed_rewards = 17

    log.operators[NodeOperatorId(0)].distributed_rewards = 0
    log.operators[NodeOperatorId(0)].performance_coefficients = PerformanceCoefficients(1, 2, 3)

    log.distributable = 100
    log.distributed_rewards = 50
    log.rebate_to_protocol = 10

    log_2 = FramePerfLog(ReferenceBlockStampFactory.build(), (EpochNumber(500), EpochNumber(900)))
    log_2.operators = log.operators

    log_2.distributable = 100000000
    log_2.distributed_rewards = 0
    log_2.rebate_to_protocol = 0

    logs = [log, log_2]

    encoded = FramePerfLog.encode(logs)

    decoded_logs = json.loads(encoded)

    for decoded in decoded_logs:
        assert decoded["operators"]["42"]["validators"]["41337"]["attestation_duty"]["assigned"] == 220
        assert decoded["operators"]["42"]["validators"]["41337"]["attestation_duty"]["included"] == 119
        assert decoded["operators"]["42"]["validators"]["41337"]["proposal_duty"]["assigned"] == 1
        assert decoded["operators"]["42"]["validators"]["41337"]["proposal_duty"]["included"] == 1
        assert decoded["operators"]["42"]["validators"]["41337"]["sync_duty"]["assigned"] == 100500
        assert decoded["operators"]["42"]["validators"]["41337"]["sync_duty"]["included"] == 100000
        assert decoded["operators"]["42"]["validators"]["41337"]["performance"] == 0.5
        assert decoded["operators"]["42"]["validators"]["41337"]["threshold"] == 0.7
        assert decoded["operators"]["42"]["validators"]["41337"]["rewards_share"] == 0.3
        assert decoded["operators"]["42"]["validators"]["41337"]["slashed"] == False
        assert decoded["operators"]["42"]["validators"]["41337"]["distributed_rewards"] == 17
        assert decoded["operators"]["42"]["distributed_rewards"] == 17
        assert decoded["operators"]["42"]["performance_coefficients"] == {
            'attestations_weight': 54,
            'blocks_weight': 8,
            'sync_weight': 2,
        }

        assert decoded["operators"]["0"]["distributed_rewards"] == 0
        assert decoded["operators"]["0"]["performance_coefficients"] == {
            'attestations_weight': 1,
            'blocks_weight': 2,
            'sync_weight': 3,
        }

    assert decoded_logs[0]["blockstamp"]["block_hash"] == log.blockstamp.block_hash
    assert decoded_logs[0]["blockstamp"]["ref_slot"] == log.blockstamp.ref_slot

    assert decoded_logs[0]["frame"] == list(log.frame)

    assert decoded_logs[0]["distributable"] == log.distributable
    assert decoded_logs[0]["distributed_rewards"] == log.distributed_rewards
    assert decoded_logs[0]["rebate_to_protocol"] == log.rebate_to_protocol

    assert decoded_logs[1]["blockstamp"]["block_hash"] == log_2.blockstamp.block_hash
    assert decoded_logs[1]["blockstamp"]["ref_slot"] == log_2.blockstamp.ref_slot

    assert decoded_logs[1]["frame"] == list(log_2.frame)

    assert decoded_logs[1]["distributable"] == log_2.distributable
    assert decoded_logs[1]["distributed_rewards"] == log_2.distributed_rewards
    assert decoded_logs[1]["rebate_to_protocol"] == log_2.rebate_to_protocol
