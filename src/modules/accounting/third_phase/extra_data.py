import itertools
from dataclasses import dataclass

from hexbytes import HexBytes

from src.modules.accounting.third_phase.types import ItemType, ExtraData, FormatList, ExtraDataLengths
from src.modules.submodules.types import ZERO_HASH
from src.types import NodeOperatorGlobalIndex
from src.web3py.types import Web3


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


class ExtraDataService:
    """
    Service that encodes extra data into bytes in correct order.

    Extra data is an array of items, each item being encoded as follows:
    |  3 bytes  | 2 bytes  |   X bytes   |
    | itemIndex | itemType | itemPayload |

    itemPayload format:
    | 3 bytes  |   8 bytes    |  nodeOpsCount * 8 bytes  |  nodeOpsCount * 16 bytes  |
    | moduleId | nodeOpsCount |      nodeOperatorIds     |   stuckOrExitedValsCount  |

    max_items_count - max itemIndex in extra data.
    max_no_in_payload_count - max nodeOpsCount that could be used in itemPayload.
    """
    @classmethod
    def collect(
        cls,
        stuck_validators: dict[NodeOperatorGlobalIndex, int],
        exited_validators: dict[NodeOperatorGlobalIndex, int],
        max_items_count: int,
        max_no_in_payload_count: int,
    ) -> ExtraData:
        stuck_payloads = cls.build_validators_payloads(stuck_validators, max_no_in_payload_count)
        exited_payloads = cls.build_validators_payloads(exited_validators, max_no_in_payload_count)

        extra_data = cls.build_extra_data(stuck_payloads, exited_payloads, max_items_count)
        extra_data_bytes = cls.to_bytes(extra_data)

        if extra_data:
            extra_data_list = [extra_data_bytes]
            data_format = FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY
            data_hash = Web3.keccak(extra_data_bytes)
        else:
            extra_data_list = []
            data_format = FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY
            data_hash = HexBytes(ZERO_HASH)

        return ExtraData(
            extra_data_list=extra_data_list,
            data_hash=data_hash,
            format=data_format.value,
            items_count=len(extra_data),
        )

    @staticmethod
    def build_validators_payloads(
        validators: dict[NodeOperatorGlobalIndex, int],
        max_no_in_payload_count: int,
    ) -> list[ItemPayload]:
        # sort by module id and node operator id
        operator_validators = sorted(validators.items(), key=lambda x: x[0])

        payloads = []

        for module_id, operators_by_module in itertools.groupby(operator_validators, key=lambda x: x[0][0]):
            operator_ids = []
            vals_count = []

            for ((_, no_id), validators_count) in list(operators_by_module)[:max_no_in_payload_count]:
                operator_ids.append(no_id.to_bytes(ExtraDataLengths.NODE_OPERATOR_ID))
                vals_count.append(validators_count.to_bytes(ExtraDataLengths.STUCK_OR_EXITED_VALS_COUNT))

            payloads.append(
                ItemPayload(
                    module_id=module_id.to_bytes(ExtraDataLengths.MODULE_ID),
                    node_ops_count=len(operator_ids).to_bytes(ExtraDataLengths.NODE_OPS_COUNT),
                    node_operator_ids=b"".join(operator_ids),
                    vals_counts=b"".join(vals_count),
                )
            )

        return payloads

    @staticmethod
    def build_extra_data(stuck_payloads: list[ItemPayload], exited_payloads: list[ItemPayload], max_items_count: int):
        index = 0
        extra_data = []

        for item_type, payloads in [
            (ItemType.EXTRA_DATA_TYPE_STUCK_VALIDATORS, stuck_payloads),
            (ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS, exited_payloads),
        ]:
            for payload in payloads:
                extra_data.append(ExtraDataItem(
                    item_index=index.to_bytes(ExtraDataLengths.ITEM_INDEX),
                    item_type=item_type,
                    item_payload=payload
                ))

                index += 1
                if index == max_items_count:
                    return extra_data

        return extra_data

    @staticmethod
    def to_bytes(extra_data: list[ExtraDataItem]) -> bytes:
        extra_data_bytes = b''
        for item in extra_data:
            extra_data_bytes += item.item_index
            extra_data_bytes += item.item_type.value.to_bytes(ExtraDataLengths.ITEM_TYPE)
            extra_data_bytes += item.item_payload.module_id
            extra_data_bytes += item.item_payload.node_ops_count
            extra_data_bytes += item.item_payload.node_operator_ids
            extra_data_bytes += item.item_payload.vals_counts
        return extra_data_bytes
