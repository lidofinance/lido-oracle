from dataclasses import dataclass
from enum import Enum
from itertools import islice
from operator import attrgetter
from src.providers.keys.typings import OperatorResponse
from src.web3_extentions.typings import Web3


# Extra data is an array of items, each item being encoded as follows:
# |  3 bytes  | 2 bytes  |   X bytes   |
# | itemIndex | itemType | itemPayload |
#
# itemPayload format:
#  | 3 bytes  |   8 bytes    |  nodeOpsCount * 8 bytes  |  nodeOpsCount * 16 bytes  |
#  | moduleId | nodeOpsCount |      nodeOperatorIds     |      stuckValsCounts      |

# TODO get from contract?
MAX_EXTRA_DATA_LIST_ITEMS_COUNT = 10


class Lengths:
    ITEM_INDEX = 3
    ITEM_TYPE = 2
    MODULE_ID = 3
    NODE_OPS_COUNT = 8
    NODE_OPERATOR_IDS = 8
    STUCK_VALS_COUNTS = 16


class ItemType(Enum):
    EXTRA_DATA_TYPE_STUCK_VALIDATORS = 0
    EXTRA_DATA_TYPE_EXITED_VALIDATORS = 1


@dataclass
class ItemPayload:
    module_id: bytes
    node_ops_count: bytes
    node_operator_ids: bytes
    stuck_vals_counts: bytes


@dataclass
class ExtraDataItem:
    item_index: bytes
    item_type: ItemType
    item_payload: ItemPayload


def chunks(it, size):
    it = iter(it)
    return iter(lambda: tuple(islice(it, size)), ())


class ExtraData:

    def __init__(self, w3: Web3):
        self.w3 = w3

    def collect(self):
        stuck_validators = self.build_stuck_validators_payloads([])
        exited_validators = self.build_exited_validators_payloads([])
        index = 0
        extra_data = []
        for item in stuck_validators + exited_validators:
            extra_data.append(ExtraDataItem(
                item_index=index.to_bytes(Lengths.ITEM_INDEX),
                item_type=ItemType.EXTRA_DATA_TYPE_STUCK_VALIDATORS,
                item_payload=item
            ))
            index += 1
        for item in stuck_validators + exited_validators:
            extra_data.append(ExtraDataItem(
                item_index=index.to_bytes(Lengths.ITEM_INDEX),
                item_type=ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS,
                item_payload=item
            ))
            index += 1
        return extra_data

    def to_bytes(self):
        extra_data = self.collect()
        extra_data_bytes = b''
        for item in extra_data:
            extra_data_bytes += item.item_index
            extra_data_bytes += item.item_type.value.to_bytes(Lengths.ITEM_TYPE)
            extra_data_bytes += item.item_payload.module_id
            extra_data_bytes += item.item_payload.node_ops_count
            extra_data_bytes += item.item_payload.node_operator_ids
            extra_data_bytes += item.item_payload.stuck_vals_counts
        return extra_data_bytes

    def build_stuck_validators_payloads(self) -> list[ItemPayload]:
        # TODO get stuck vals count
        return self.build_validators_payloads([])

    def build_exited_validators_payloads(self) -> list[ItemPayload]:
        # TODO get exited vals count
        return self.build_validators_payloads([])

    def build_validators_payloads(self, operator_response: list[OperatorResponse]) -> list[ItemPayload]:
        payloads = []
        operator_response.sort(key=lambda x: (x.module.id, x.operators[0].index))
        for operators in operator_response:
            operators_list = sorted(operators.operators, key=attrgetter('index'))
            for chunk in chunks(operators_list, MAX_EXTRA_DATA_LIST_ITEMS_COUNT):
                node_operator_ids = []
                vals_count = []
                for operator in chunk:
                    node_operator_ids.append(operator.index.to_bytes(Lengths.NODE_OPERATOR_IDS))
                    # TODO how to count it
                    vals_count.append(int.to_bytes(0, Lengths.STUCK_VALS_COUNTS))
                payloads.append(ItemPayload(
                    module_id=operators.module.id.to_bytes(Lengths.MODULE_ID),
                    node_ops_count=len(chunk).to_bytes(Lengths.NODE_OPS_COUNT),
                    node_operator_ids=b"".join(node_operator_ids),
                    stuck_vals_counts=b"".join(vals_count),
                ))
        return payloads
