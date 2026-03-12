import pytest
from pydantic import ValidationError

from src.modules.sidecars.performance.web.validation import (
    ConsumerParam,
    EpochParam,
    EpochRangeParam,
    EpochsDemandParam,
    LimitedEpochRangeParam,
)
from src.types import EpochNumber
from src.variables import PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE


pytestmark = pytest.mark.unit


class TestConsumerParam:
    def test_rejects_blank(self):
        with pytest.raises(ValidationError):
            ConsumerParam(consumer="   ")

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            ConsumerParam(consumer="")

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError):
            ConsumerParam(consumer="x" * 256)

    def test_accepts_valid(self):
        result = ConsumerParam(consumer="oracle-1")
        assert result.consumer == "oracle-1"


class TestEpochRangeParam:
    def test_rejects_negative_epoch(self):
        with pytest.raises(ValidationError):
            EpochRangeParam.model_validate({"from_epoch": -1, "to_epoch": 1})

        with pytest.raises(ValidationError):
            EpochRangeParam.model_validate({"from_epoch": 1, "to_epoch": -1})

    def test_rejects_from_greater_than_to(self):
        with pytest.raises(ValidationError):
            EpochRangeParam.model_validate({"from_epoch": 2, "to_epoch": 1})

    def test_accepts_valid(self):
        result = EpochRangeParam.model_validate({"from_epoch": 1, "to_epoch": 2})
        assert result.from_epoch == 1
        assert result.to_epoch == 2

    def test_accepts_alias_fields(self):
        result = EpochRangeParam.model_validate({"from": 1, "to": 2})
        assert result.from_epoch == 1
        assert result.to_epoch == 2


class TestLimitedEpochRangeParam:
    def test_rejects_range_too_large(self):
        with pytest.raises(ValidationError):
            LimitedEpochRangeParam.model_validate({"from_epoch": 0, "to_epoch": PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE})

    def test_accepts_within_limit(self):
        upper_bound = PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE - 1
        result = LimitedEpochRangeParam.model_validate({"from_epoch": 0, "to_epoch": upper_bound})
        assert result.from_epoch == 0
        assert result.to_epoch == upper_bound


class TestEpochParam:
    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            EpochParam(epoch=EpochNumber(-1))

    def test_accepts_valid(self):
        result = EpochParam(epoch=EpochNumber(42))
        assert result.epoch == 42


class TestEpochsDemandParam:
    def test_validates_consumer_and_range(self):
        result = EpochsDemandParam(consumer="oracle-1", from_epoch=EpochNumber(10), to_epoch=EpochNumber(20))
        assert result.consumer == "oracle-1"
        assert result.from_epoch == 10
        assert result.to_epoch == 20

    def test_rejects_blank_consumer(self):
        with pytest.raises(ValidationError):
            EpochsDemandParam(consumer="   ", from_epoch=EpochNumber(10), to_epoch=EpochNumber(20))

    def test_rejects_invalid_epoch_range(self):
        with pytest.raises(ValidationError):
            EpochsDemandParam(consumer="oracle-1", from_epoch=EpochNumber(20), to_epoch=EpochNumber(10))
