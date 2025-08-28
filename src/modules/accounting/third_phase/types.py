from dataclasses import dataclass
from enum import Enum


class ItemType(Enum):
    # Deprecated with TW upgrade
    # EXTRA_DATA_TYPE_STUCK_VALIDATORS = 1
    EXTRA_DATA_TYPE_EXITED_VALIDATORS = 2


class FormatList(Enum):
    EXTRA_DATA_FORMAT_LIST_EMPTY = 0
    EXTRA_DATA_FORMAT_LIST_NON_EMPTY = 1


@dataclass
class ExtraData:
    extra_data_list: list[bytes]
    data_hash: bytes
    format: int
    items_count: int


class ExtraDataLengths:
    ITEM_INDEX = 3
    ITEM_TYPE = 2
    MODULE_ID = 3
    NODE_OPS_COUNT = 8
    NODE_OPERATOR_ID = 8
    EXITED_VALS_COUNT = 16
