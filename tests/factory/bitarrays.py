from typing import Sequence

from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import BaseModel


class BitList(BaseModel):
    __root__: bytes

    def hex(self) -> str:
        return f"0x{self.__root__.hex()}"


class BitListFactory(ModelFactory):
    __model__ = BitList

    @classmethod
    def build(
        cls,
        factory_use_construct: bool = False,
        set_indices: list[int] = [],
        bits_count: int = 0,
        **kwargs,
    ) -> BitList:
        bit_list: list[bool] = []
        for n in sorted(set_indices):
            while len(bit_list) < n:
                bit_list += [False]
            bit_list += [True]

        model = cls._get_model()
        return model(
            __root__=get_serialized_bytearray(
                bit_list,
                bits_count=bits_count or len(bit_list),
                extra_byte=True,
            )
        )


def get_serialized_bytearray(value: Sequence[bool], bits_count: int, extra_byte: bool) -> bytearray:
    """
    Serialize a sequence either into a Bitlist or a Bitvector
    @see https://github.com/ethereum/py-ssz/blob/main/ssz/utils.py#L223
    """

    if extra_byte:
        # Serialize Bitlist
        as_bytearray = bytearray(bits_count // 8 + 1)
    else:
        # Serialize Bitvector
        as_bytearray = bytearray((bits_count + 7) // 8)

    for i in range(bits_count):
        as_bytearray[i // 8] |= value[i] << (i % 8)

    if extra_byte:
        as_bytearray[bits_count // 8] |= 1 << (bits_count % 8)

    return as_bytearray
