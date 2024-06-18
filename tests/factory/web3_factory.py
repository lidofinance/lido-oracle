import random
from contextlib import suppress
from dataclasses import is_dataclass
from enum import EnumMeta
from inspect import isclass
from typing import Any, NewType, cast

from eth_typing import HexAddress, HexStr
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from pydantic import BaseModel
from pydantic.fields import ModelField
from pydantic_factories import ModelFactory
from pydantic_factories.exceptions import ParameterError
from pydantic_factories.factory import T
from pydantic_factories.utils import is_literal, is_pydantic_model, unwrap_new_type_if_needed
from pydantic_factories.value_generators.complex_types import handle_complex_type
from typing_extensions import get_args, is_typeddict


class Web3Factory(ModelFactory[Any]):
    """Tweak the ModelFactory to add our web3 types."""

    __auto_register__ = True
    __model__ = BaseModel

    @classmethod
    def get_field_value(cls, model_field: "ModelField", field_parameters: dict | list | None = None) -> Any:
        """Returns a field value on the subclass if existing, otherwise returns a mock value.

        Args:
            model_field: A pydantic 'ModelField'.
            field_parameters: Any parameters related to the model field.

        Returns:
            An arbitrary value.
        """
        if model_field.field_info.const:
            return model_field.get_default()

        if cls.should_set_none_value(model_field=model_field):
            return None

        outer_type = unwrap_new_type_if_needed(model_field.outer_type_)
        if isinstance(outer_type, EnumMeta):
            return cls._handle_enum(cast("Type[Enum]", outer_type))

        if is_pydantic_model(outer_type) or is_dataclass(outer_type) or is_typeddict(outer_type):
            return cls._get_or_create_factory(model=outer_type).build(
                **(field_parameters if isinstance(field_parameters, dict) else {})
            )

        if isinstance(field_parameters, list) and is_pydantic_model(model_field.type_):
            return [
                cls._get_or_create_factory(model=model_field.type_).build(**build_kwargs)
                for build_kwargs in field_parameters
            ]

        if cls.is_constrained_field(outer_type):
            return cls._handle_constrained_field(model_field=model_field)

        if model_field.sub_fields:
            return handle_complex_type(model_field=model_field, model_factory=cls, field_parameters=field_parameters)

        if is_literal(model_field):
            literal_args = get_args(outer_type)
            return random.choice(literal_args)

        # this is a workaround for the following issue: https://github.com/samuelcolvin/pydantic/issues/3415
        field_type = unwrap_new_type_if_needed(model_field.type_) if model_field.type_ is not Any else outer_type
        if cls.is_ignored_type(field_type):
            return None

        annotation = cls._get_annotation(field_name=model_field.name)

        return cls.get_mock_value(field_type=annotation)

    @classmethod
    def _get_annotation(cls, field_name: str) -> str:
        model = cls._get_model()

        while True:
            annotation = model.__annotations__.get(field_name)
            if annotation:
                return annotation

            model = model.__base__

    @classmethod
    def get_provider_map(cls):
        return {
            **super().get_provider_map(),
            **cls.get_web3_provider_map(),
        }

    @classmethod
    def get_web3_provider_map(cls):
        faker = cls.get_faker()

        return {
            str: faker.pyint,
            HexAddress: lambda: to_checksum_address(HexBytes(faker.binary(length=20)).hex()),
            HexStr: lambda: HexBytes(faker.binary(length=20)).hex(),
            HexBytes: lambda: HexBytes(faker.binary(length=64)),
            int | None: lambda: None,
        }

    @classmethod
    def get_mock_value(cls, field_type: Any) -> Any:
        """Returns a mock value for a given type.

        Args:
            field_type: An arbitrary type.

        Returns:
            An arbitrary value.
        """
        handler = cls.get_provider_map().get(field_type)
        if handler is not None:
            return handler()

        if isinstance(field_type, NewType):
            return cls.get_mock_value(field_type.__supertype__)

        if isclass(field_type):
            # if value is a class we can try to naively instantiate it.
            # this will work for classes that do not require any parameters passed to __init__
            with suppress(Exception):
                return field_type()
        raise ParameterError(
            f"Unsupported type: {field_type!r}"
            f"\n\nEither extend the providers map or add a factory function for this model field"
        )

    @classmethod
    def batch_with(cls, field_name: str, field_values: list[Any], **kwargs: Any) -> T:
        result = []

        for value in field_values:
            kwargs[field_name] = value
            result.append(cls.build(**kwargs))

        return result
