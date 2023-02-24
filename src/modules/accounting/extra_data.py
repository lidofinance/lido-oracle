import itertools
from dataclasses import dataclass
from enum import Enum
from itertools import islice

from hexbytes import HexBytes

from src.web3py.extentions.lido_validators import NodeOperatorIndex
from src.web3py.typings import Web3


class Lengths:
    ITEM_INDEX = 3
    ITEM_TYPE = 2
    MODULE_ID = 3
    NODE_OPS_COUNT = 8
    NODE_OPERATOR_IDS = 8
    STUCK_AND_EXITED_VALS_COUNT = 16


class ItemType(Enum):
    EXTRA_DATA_TYPE_STUCK_VALIDATORS = 0
    EXTRA_DATA_TYPE_EXITED_VALIDATORS = 1


class FormatList(Enum):
    # TODO old contracts have 1, new contracts have 0, don't forget to change it
    EXTRA_DATA_FORMAT_LIST_EMPTY = 1
    EXTRA_DATA_FORMAT_LIST_NON_EMPTY = 1


@dataclass
class ItemPayload:
    module_id: bytes
    node_ops_count: bytes
    node_operator_ids: bytes
    vals_counts: bytes


@dataclass
class ExtraDataItem:
    item_index: bytes
    item_type: ItemType
    item_payload: ItemPayload


@dataclass
class ExtraData:
    extra_data: bytes
    data_hash: HexBytes
    format: int
    items_count: int


def chunks(it, size):
    it = iter(it)
    return iter(lambda: tuple(islice(it, size)), ())


class ExtraDataService:
    def __init__(self, w3: Web3):
        self.w3 = w3

    def collect(
        self,
        exited_validators: dict[NodeOperatorIndex, int],
        stuck_validators: dict[NodeOperatorIndex, int],
        max_items_in_payload_count: int,
        max_items_count: int,
    ) -> ExtraData:
        stuck_payloads = self.build_validators_payloads(stuck_validators, max_items_in_payload_count)
        exited_payloads = self.build_validators_payloads(exited_validators, max_items_in_payload_count)

        extra_data = self.build_extra_data(stuck_payloads, exited_payloads, max_items_count)
        extra_data_bytes = self.to_bytes(extra_data)

        data_format = FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY if extra_data else FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY
        return ExtraData(
            extra_data=extra_data_bytes,
            data_hash=self.w3.keccak(extra_data_bytes),
            format=data_format.value,
            items_count=len(extra_data),
        )

    def to_bytes(self, extra_data: list[ExtraDataItem]) -> bytes:
        # Extra data is an array of items, each item being encoded as follows:
        # |  3 bytes  | 2 bytes  |   X bytes   |
        # | itemIndex | itemType | itemPayload |
        #
        # itemPayload format:
        #  | 3 bytes  |   8 bytes    |  nodeOpsCount * 8 bytes  |  nodeOpsCount * 16 bytes  |
        #  | moduleId | nodeOpsCount |      nodeOperatorIds     |   stuckOrExitedValsCount  |
        extra_data_bytes = b''
        for item in extra_data:
            extra_data_bytes += item.item_index
            extra_data_bytes += item.item_type.value.to_bytes(Lengths.ITEM_TYPE)
            extra_data_bytes += item.item_payload.module_id
            extra_data_bytes += item.item_payload.node_ops_count
            extra_data_bytes += item.item_payload.node_operator_ids
            extra_data_bytes += item.item_payload.vals_counts
        return extra_data_bytes

    @staticmethod
    def build_extra_data(stuck_payloads: list[ItemPayload], exited_payloads: list[ItemPayload], max_items_count: int):
        index = 0
        extra_data = []
        total_items_count = 0

        for item_type, payloads in [
            (ItemType.EXTRA_DATA_TYPE_STUCK_VALIDATORS, stuck_payloads),
            (ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS, exited_payloads),
        ]:
            for item in payloads:
                total_items_count += int.from_bytes(item.node_ops_count)
                if total_items_count > max_items_count:
                    return extra_data

                extra_data.append(ExtraDataItem(
                    item_index=index.to_bytes(Lengths.ITEM_INDEX),
                    item_type=item_type,
                    item_payload=item
                ))
                index += 1

        return extra_data

    @staticmethod
    def build_validators_payloads(validators: dict[NodeOperatorIndex, int], max_list_items_count: int) -> list[ItemPayload]:
        # sort by module id and node operator id
        operator_validators = sorted(validators.items(), key=lambda x: (x[0][0], x[0][1]))
        payloads = []

        for module_id, group in itertools.groupby(operator_validators, key=lambda x: x[0][0]):
            for chunk in chunks(group, max_list_items_count):
                operator_ids = []
                vals_count = []
                for (_, operator_id), validators_count in chunk:
                    operator_ids.append(operator_id.to_bytes(Lengths.NODE_OPERATOR_IDS))
                    vals_count.append(validators_count.to_bytes(Lengths.STUCK_AND_EXITED_VALS_COUNT))

                payloads.append(ItemPayload(
                    module_id=module_id.to_bytes(Lengths.MODULE_ID),
                    node_ops_count=len(chunk).to_bytes(Lengths.NODE_OPS_COUNT),
                    node_operator_ids=b"".join(operator_ids),
                    vals_counts=b"".join(vals_count),
                ))
        return payloads
