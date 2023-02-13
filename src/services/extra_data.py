from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from itertools import islice
from operator import itemgetter

from src.providers.keys.typings import LidoKey, ContractModule
from src.typings import BlockStamp
from src.web3_extentions.typings import Web3


# Extra data is an array of items, each item being encoded as follows:
# |  3 bytes  | 2 bytes  |   X bytes   |
# | itemIndex | itemType | itemPayload |
#
# itemPayload format:
#  | 3 bytes  |   8 bytes    |  nodeOpsCount * 8 bytes  |  nodeOpsCount * 16 bytes  |
#  | moduleId | nodeOpsCount |      nodeOperatorIds     |      stuckValsCounts      |

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
    vals_counts: bytes


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

    def collect(self, blockstamp: BlockStamp, exited_validators: list[LidoKey], stucked_validators: list[LidoKey]) -> bytes:
        operators_response = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        # TODO get from oracleReportSanityChecker contract
        max_extra_data_list_items_count = 100
        stucked_payloads = self.build_validators_payloads(stucked_validators, max_extra_data_list_items_count)
        exited_payloads = self.build_validators_payloads(exited_validators, max_extra_data_list_items_count)

        extra_data = self.build_extra_data(stucked_payloads, exited_payloads)
        return self.to_bytes(extra_data)

    def to_bytes(self, extra_data: list[ExtraDataItem]) -> bytes:
        extra_data_bytes = b''
        for item in extra_data:
            extra_data_bytes += item.item_index
            extra_data_bytes += item.item_type.value.to_bytes(Lengths.ITEM_TYPE)
            extra_data_bytes += item.item_payload.module_id
            extra_data_bytes += item.item_payload.node_ops_count
            extra_data_bytes += item.item_payload.node_operator_ids
            extra_data_bytes += item.item_payload.vals_counts
        return self.w3.keccak(extra_data_bytes)

    def build_extra_data(self, stucked_payloads: list[ItemPayload], exited_payloads: list[ItemPayload]):
        index = 0
        extra_data = []
        for item in stucked_payloads:
            extra_data.append(ExtraDataItem(
                item_index=index.to_bytes(Lengths.ITEM_INDEX),
                item_type=ItemType.EXTRA_DATA_TYPE_STUCK_VALIDATORS,
                item_payload=item
            ))
            index += 1
        for item in exited_payloads:
            extra_data.append(ExtraDataItem(
                item_index=index.to_bytes(Lengths.ITEM_INDEX),
                item_type=ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS,
                item_payload=item
            ))
            index += 1
        return extra_data

    def build_validators_payloads(self, validators: list[LidoKey], modules: list[ContractModule], max_extra_data_list_items_count) -> list[ItemPayload]:
        payloads = []
        module_to_operators = {}

        for module in modules:
            module_to_operators[module.stakingModuleAddress] = {"module": module, "operators": defaultdict(list)}
        for validator in validators:
            module_to_operators[validator.moduleAddress]["operators"][validator.operatorIndex].append(validator)

        for mapping in sorted(module_to_operators.values(), key=lambda x: x["module"].id):
            module = mapping["module"]
            operators = mapping["operators"]
            operators = sorted(operators.items(), key=itemgetter(0))
            for chunk in chunks(operators, max_extra_data_list_items_count):
                operator_ids = []
                vals_count = []
                for operator_id, validators in chunk:
                    operator_ids.append(operator_id.to_bytes(Lengths.NODE_OPERATOR_IDS))
                    vals_count.append(len(validators).to_bytes(Lengths.STUCK_VALS_COUNTS))
                payloads.append(ItemPayload(
                    module_id=module.id.to_bytes(Lengths.MODULE_ID),
                    node_ops_count=len(chunk).to_bytes(Lengths.NODE_OPS_COUNT),
                    node_operator_ids=b"".join(operator_ids),
                    vals_counts=b"".join(vals_count),
                ))
        return payloads
