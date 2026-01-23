from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

from src.types import EpochNumber
from src.variables import PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE


class ConsumerParam(BaseModel):
    consumer: str = Field(..., min_length=1, max_length=255)

    @classmethod
    @field_validator("consumer")
    def consumer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("consumer cannot be blank")
        return value


class EpochRangeBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_epoch: EpochNumber
    to_epoch: EpochNumber

    @classmethod
    @field_validator("from_epoch", "to_epoch", mode="before")
    def epoch_not_negative(cls, value: EpochNumber) -> EpochNumber:
        if int(value) < 0:
            raise ValueError("epoch must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_epoch_bounds(self):
        from_label = self.model_fields["from_epoch"].alias or "from_epoch"
        to_label = self.model_fields["to_epoch"].alias or "to_epoch"
        if self.from_epoch > self.to_epoch:
            raise ValueError(f"'{from_label}' must be <= '{to_label}'")
        return self


class EpochRangeQuery(EpochRangeBase):
    from_epoch: EpochNumber = Field(..., alias="from")
    to_epoch: EpochNumber = Field(..., alias="to")


class LimitedEpochRangeQuery(EpochRangeQuery):
    @model_validator(mode="after")
    def validate_range_size(self):
        range_size = int(self.to_epoch) - int(self.from_epoch) + 1
        if range_size > PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE:
            raise ValueError(
                f"Requested epoch range is too large; maximum allowed size is {PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE} epochs"
            )
        return self


class EpochPath(BaseModel):
    epoch: EpochNumber

    @classmethod
    @field_validator("epoch", mode="before")
    def epoch_not_negative(cls, value: EpochNumber) -> EpochNumber:
        if int(value) < 0:
            raise ValueError("epoch must be non-negative")
        return value


class EpochsDemandRequest(ConsumerParam, EpochRangeBase):
    pass


class EpochsDemandResponse(ConsumerParam, EpochRangeBase):
    model_config = ConfigDict(from_attributes=True)


def parse_epoch_range_query(
    from_epoch: Annotated[EpochNumber, Query(..., alias="from")],
    to_epoch: Annotated[EpochNumber, Query(..., alias="to")],
) -> EpochRangeQuery:
    return EpochRangeQuery.model_validate({"from_epoch": from_epoch, "to_epoch": to_epoch})


def parse_limited_epoch_range_query(
    from_epoch: Annotated[EpochNumber, Query(..., alias="from")],
    to_epoch: Annotated[EpochNumber, Query(..., alias="to")],
) -> LimitedEpochRangeQuery:
    return LimitedEpochRangeQuery.model_validate({"from_epoch": from_epoch, "to_epoch": to_epoch})
