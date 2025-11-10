import struct
from dataclasses import dataclass
from typing import TypeAlias

from pyroaring import BitMap

from src.types import ValidatorIndex


@dataclass
class ProposalDuty:
    validator_index: int
    is_proposed: bool


class ProposalDutiesCodec:
    # little-endian | uint64 validator_index | bool is_proposed
    # See: https://docs.python.org/3/library/struct.html#format-characters
    PACK_FMT = "<Q?"
    ITEM_SIZE = struct.calcsize(PACK_FMT)

    @classmethod
    def encode(cls, proposals: list[ProposalDuty]) -> bytes:
        items = sorted(((p.validator_index, p.is_proposed) for p in proposals), key=lambda t: t[0])
        return b"".join(struct.pack(cls.PACK_FMT, vid, flag) for vid, flag in items)

    @classmethod
    def decode(cls, blob: bytes) -> list[ProposalDuty]:
        out: list[ProposalDuty] = []
        if not blob:
            return out
        if len(blob) % cls.ITEM_SIZE != 0:
            raise ValueError("Invalid proposals bytes length")
        for i in range(0, len(blob), cls.ITEM_SIZE):
            vid, p = struct.unpack_from(cls.PACK_FMT, blob, i)
            out.append(ProposalDuty(validator_index=int(vid), is_proposed=p))
        return out


@dataclass
class SyncDuty:
    validator_index: int
    missed_count: int  # 0..32


class SyncDutiesCodec:
    # little-endian | uint64 validator_index | uint8 missed_count
    # See: https://docs.python.org/3/library/struct.html#format-characters
    PACK_FMT = "<QB"
    ITEM_SIZE = struct.calcsize(PACK_FMT)

    @classmethod
    def encode(cls, syncs: list[SyncDuty]) -> bytes:
        if len(syncs) == 0:
            raise ValueError("Invalid syncs count")
        items_sorted = sorted(((m.validator_index, m.missed_count) for m in syncs), key=lambda t: t[0])
        return b"".join(struct.pack(cls.PACK_FMT, vid, cnt) for vid, cnt in items_sorted)

    @classmethod
    def decode(cls, blob: bytes) -> list[SyncDuty]:
        out: list[SyncDuty] = []
        if not blob:
            return out
        if len(blob) % cls.ITEM_SIZE != 0:
            raise ValueError("invalid sync misses bytes length")
        for i in range(0, len(blob), cls.ITEM_SIZE):
            vid, m = struct.unpack_from(cls.PACK_FMT, blob, i)
            out.append(SyncDuty(validator_index=int(vid), missed_count=int(m)))
        return out


AttDutyMisses: TypeAlias = set[ValidatorIndex]


class AttDutiesMissCodec:

    @staticmethod
    def encode(misses: AttDutyMisses) -> bytes:
        bm = BitMap(sorted(v for v in misses))
        bm.shrink_to_fit()
        bm.run_optimize()
        return bm.serialize()

    @staticmethod
    def decode(blob: bytes) -> AttDutyMisses:
        # Non-iterable value BitMap.deserialize(blob) is used in an iterating context,
        # but it IS iterable.
        return {ValidatorIndex(i) for i in BitMap.deserialize(blob)}  # pylint: disable=E1133


EpochData: TypeAlias = tuple[AttDutyMisses, list[ProposalDuty], list[SyncDuty]]


class EpochDataCodec:
    # little-endian | uint8 version | uint32 att_count | uint8 prop_count | uint16 sync_count
    # See: https://docs.python.org/3/library/struct.html#format-characters
    HEADER_FMT = "<BIBH"
    HEADER_SIZE = struct.calcsize(HEADER_FMT)
    VERSION = 1

    @classmethod
    def encode(
        cls,
        att_misses: set[ValidatorIndex],
        proposals: list[ProposalDuty],
        syncs: list[SyncDuty],
    ) -> bytes:
        att_bytes = AttDutiesMissCodec.encode(att_misses)
        prop_bytes = ProposalDutiesCodec.encode(proposals)
        sync_bytes = SyncDutiesCodec.encode(syncs)
        header = struct.pack(cls.HEADER_FMT, cls.VERSION, len(att_bytes), len(proposals), len(syncs))
        return header + prop_bytes + sync_bytes + att_bytes

    @classmethod
    def decode(cls, blob: bytes) -> EpochData:
        if len(blob) < cls.HEADER_SIZE:
            raise ValueError(f"Epoch blob too short to decode: header size is {cls.HEADER_SIZE} but full blob size is {len(blob)}")
        ver, att_count, prop_count, sync_count = struct.unpack_from(cls.HEADER_FMT, blob, 0)
        if ver != cls.VERSION:
            raise ValueError(f"Unsupported epoch blob version: {ver}")
        props_size = int(prop_count) * ProposalDutiesCodec.ITEM_SIZE
        sync_size = int(sync_count) * SyncDutiesCodec.ITEM_SIZE
        expected_blob_size = cls.HEADER_SIZE + props_size + sync_size + att_count
        if len(blob) < expected_blob_size:
            raise ValueError(f"Epoch blob size mismatch: expected {expected_blob_size} but got {len(blob)}")
        offset = cls.HEADER_SIZE
        props = ProposalDutiesCodec.decode(blob[offset:(offset + props_size)])
        offset += props_size
        syncs = SyncDutiesCodec.decode(blob[offset:(offset + sync_size)])
        offset += sync_size
        att = AttDutiesMissCodec.decode(bytes(blob[offset:(offset + att_count)])) if att_count else BitMap()
        return set(att), props, syncs
