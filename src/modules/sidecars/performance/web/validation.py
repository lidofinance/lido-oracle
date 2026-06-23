from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.types import EpochNumber
from src.variables import PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE


# PostgreSQL INTEGER max value (4 bytes, signed)
PG_INTEGER_MAX = 2_147_483_647


class ConsumerParam(BaseModel):
    consumer: str = Field(..., min_length=1, max_length=255)

    @field_validator("consumer")
    def consumer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("consumer cannot be blank")
        return value


class EpochRangeBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_epoch: EpochNumber
    to_epoch: EpochNumber

    @field_validator("from_epoch", "to_epoch")
    @classmethod
    def validate_epoch(cls, value: EpochNumber) -> EpochNumber:
        if value < 0:
            raise ValueError("epoch must be non-negative")
        if value > PG_INTEGER_MAX:
            raise ValueError(f"epoch must not exceed {PG_INTEGER_MAX}")
        return value

    @model_validator(mode="after")
    def validate_epoch_bounds(self):
        if self.from_epoch > self.to_epoch:
            raise ValueError("start epoch must be less than or equal to the end one")
        return self


class EpochRangeParam(EpochRangeBase):
    from_epoch: EpochNumber = Field(..., alias="from")
    to_epoch: EpochNumber = Field(..., alias="to")


class LimitedEpochRangeParam(EpochRangeParam):
    @model_validator(mode="after")
    def validate_range_size(self):
        range_size = self.to_epoch - self.from_epoch + 1
        if range_size > PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE:
            raise ValueError(
                "Requested epoch range is too large; maximum allowed size is "
                f"{PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE} epochs"
            )
        return self


class EpochParam(BaseModel):
    epoch: EpochNumber

    @field_validator("epoch")
    @classmethod
    def validate_epoch(cls, value: EpochNumber) -> EpochNumber:
        if value < 0:
            raise ValueError("epoch must be non-negative")
        if value > PG_INTEGER_MAX:
            raise ValueError(f"epoch must not exceed {PG_INTEGER_MAX}")
        return value


class EpochsDemandParam(ConsumerParam, EpochRangeBase):
    pass


class EpochsDemandResponse(ConsumerParam, EpochRangeBase):
    updated_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class RetentionEpochsParam(BaseModel):
    retention_epochs: int = Field(..., gt=0)


class RetentionEpochsResponse(BaseModel):
    retention_epochs: int
