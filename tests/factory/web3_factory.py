from dataclasses import is_dataclass, MISSING, fields
from typing import TypeVar, Generic, TypeGuard, Any, get_type_hints

from eth_typing import HexStr, HexAddress
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from polyfactory import BaseFactory
from polyfactory.field_meta import FieldMeta, Null

T = TypeVar("T")


class Web3DataclassFactory(Generic[T], BaseFactory[T]):
    """Dataclass base factory"""

    __is_base_factory__ = True

    @classmethod
    def is_supported_type(cls, value: Any) -> TypeGuard[type[T]]:
        """Determine whether the given value is supported by the factory.

        :param value: An arbitrary value.
        :returns: A typeguard
        """
        return bool(is_dataclass(value))

    @classmethod
    def get_model_fields(cls) -> list["FieldMeta"]:
        """Retrieve a list of fields from the factory's model.


        :returns: A list of field MetaData instances.

        """
        fields_meta: list["FieldMeta"] = []

        model_type_hints = get_type_hints(cls.__model__, include_extras=True)

        for field in fields(cls.__model__):  # type: ignore[arg-type]
            if not field.init:
                continue

            if field.default_factory and field.default_factory is not MISSING:
                default_value = field.default_factory()
            elif field.default is not MISSING:
                default_value = field.default
            else:
                default_value = Null

            fields_meta.append(
                FieldMeta.from_type(
                    annotation=model_type_hints[field.name],
                    name=field.name,
                    default=default_value,
                    random=cls.__random__,
                ),
            )

        return fields_meta

    @classmethod
    def get_provider_map(cls):
        return {
            **super().get_provider_map(),
            **cls.get_web3_provider_map(),
        }

    @classmethod
    def get_web3_provider_map(cls):
        faker = cls.__faker__

        return {
            str: faker.pyint,
            HexAddress: lambda: to_checksum_address(HexBytes(faker.binary(length=20)).hex()),
            HexStr: lambda: HexBytes(faker.binary(length=20)).hex(),
            HexBytes: lambda: HexBytes(faker.binary(length=64)),
            int | None: lambda: None,
        }
