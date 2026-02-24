from typing import Annotated

from fastapi import Path, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from src.types import EpochNumber
from src.variables import PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE


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

    @field_validator("from_epoch", "to_epoch", mode="before")
    def epoch_not_negative(cls, value: EpochNumber) -> EpochNumber:
        if int(value) < 0:
            raise ValueError("epoch must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_epoch_bounds(self):
        model_fields = type(self).model_fields
        from_label = model_fields["from_epoch"].alias or "from_epoch"
        to_label = model_fields["to_epoch"].alias or "to_epoch"
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
                "Requested epoch range is too large; maximum allowed size is "
                f"{PERFORMANCE_WEB_SERVER_MAX_EPOCH_RANGE} epochs"
            )
        return self


class EpochPath(BaseModel):
    epoch: EpochNumber

    @field_validator("epoch", mode="before")
    def epoch_not_negative(cls, value: EpochNumber) -> EpochNumber:
        if int(value) < 0:
            raise ValueError("epoch must be non-negative")
        return value


class EpochsDemandRequest(ConsumerParam, EpochRangeBase):
    pass


class EpochsDemandResponse(ConsumerParam, EpochRangeBase):
    updated_at: int
    model_config = ConfigDict(from_attributes=True)


def parse_epoch_range_query(
    from_epoch: Annotated[EpochNumber, Query(..., alias="from")],
    to_epoch: Annotated[EpochNumber, Query(..., alias="to")],
) -> EpochRangeQuery:
    try:
        return EpochRangeQuery.model_validate({"from_epoch": from_epoch, "to_epoch": to_epoch})
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


def parse_limited_epoch_range_query(
    from_epoch: Annotated[EpochNumber, Query(..., alias="from")],
    to_epoch: Annotated[EpochNumber, Query(..., alias="to")],
) -> LimitedEpochRangeQuery:
    try:
        return LimitedEpochRangeQuery.model_validate({"from_epoch": from_epoch, "to_epoch": to_epoch})
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


def parse_consumer_path(
    consumer: Annotated[str, Path(...)],
) -> ConsumerParam:
    try:
        return ConsumerParam.model_validate({"consumer": consumer})
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


def parse_epoch_path(
    epoch: Annotated[EpochNumber, Path(...)],
) -> EpochPath:
    try:
        return EpochPath.model_validate({"epoch": epoch})
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error
