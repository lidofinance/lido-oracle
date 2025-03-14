from typing import Sequence

from polyfactory.factories.pydantic_factory import ModelFactory
from pydantic import RootModel


class BitList(RootModel):
    root: bytes

    def hex(self) -> str:
        return f"0x{self.root.hex()}"


class BitListFactory(ModelFactory[BitList]):
    @classmethod
    def build(
        cls,
        set_indices: list[int] = None,
        bits_count: int = 0,
    ) -> BitList:
        set_indices = set_indices or []
        bit_list: list[bool] = [False] * (max(set_indices, default=0) + 1)
        for n in set_indices:
            bit_list[n] = True
        bytearray = get_serialized_bytearray(
            bit_list,
            bits_count=bits_count or len(bit_list),
            extra_byte=True,
        )
        return cls.__model__(bytes(bytearray))


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
