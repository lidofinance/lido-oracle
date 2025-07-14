from dataclasses import dataclass
from itertools import groupby, batched
from typing import Sequence

from src.modules.accounting.third_phase.types import ExtraData, ItemType, ExtraDataLengths, FormatList
from src.modules.submodules.types import ZERO_HASH
from src.types import NodeOperatorGlobalIndex
from src.web3py.types import Web3


@dataclass
class ItemPayload:
    module_id: int
    node_operator_ids: Sequence[int]
    vals_counts: Sequence[int]


class ExtraDataService:
    """
    Service that encodes extra data into bytes in correct order.

    Extra data is an array of items, each item being encoded as follows:
    | 32 bytes |  3 bytes  | 2 bytes  |   X bytes   |
    | nextHash | itemIndex | itemType | itemPayload |

    itemPayload format:
    | 3 bytes  |   8 bytes    |  nodeOpsCount * 8 bytes  |  nodeOpsCount * 16 bytes  |
    | moduleId | nodeOpsCount |      nodeOperatorIds     |   exitedValsCount  |

    max_items_count_per_tx - max itemIndex in extra data.
    max_no_in_payload_count - max nodeOpsCount that could be used in itemPayload.
    """
    @classmethod
    def collect(
        cls,
        exited_validators: dict[NodeOperatorGlobalIndex, int],
        max_items_count_per_tx: int,
        max_no_in_payload_count: int,
    ) -> ExtraData:
        exited_payloads = cls.build_validators_payloads(exited_validators, max_no_in_payload_count)
        items_count, txs = cls.build_extra_transactions_data(exited_payloads, max_items_count_per_tx)
        first_hash, hashed_txs = cls.add_hashes_to_transactions(txs)

        if items_count:
            extra_data_format = FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY
        else:
            extra_data_format = FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY

        return ExtraData(
            items_count=items_count,
            extra_data_list=hashed_txs,
            data_hash=first_hash,
            format=extra_data_format.value,
        )

    @classmethod
    def build_validators_payloads(
        cls,
        validators: dict[NodeOperatorGlobalIndex, int],
        max_no_in_payload_count: int,
    ) -> list[ItemPayload]:
        operator_validators = sorted(validators.items(), key=lambda x: x[0])

        payloads = []

        for module_id, operators_by_module in groupby(operator_validators, key=lambda x: x[0][0]):
            for nos_in_batch in batched(list(operators_by_module), max_no_in_payload_count):
                operator_ids = []
                vals_count = []

                for ((_, no_id), validators_count) in nos_in_batch:
                    operator_ids.append(no_id)
                    vals_count.append(validators_count)

                payloads.append(
                    ItemPayload(
                        module_id=module_id,
                        node_operator_ids=operator_ids,
                        vals_counts=vals_count,
                    )
                )

        return payloads

    @classmethod
    def build_extra_transactions_data(
        cls,
        exited_payloads: list[ItemPayload],
        max_items_count_per_tx: int,
    ) -> tuple[int, list[bytes]]:
        all_payloads = [
            *[(ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS, payload) for payload in exited_payloads],
        ]

        index = 0
        result = []

        for payload_batch in batched(all_payloads, max_items_count_per_tx):
            tx_body = b''
            for item_type, payload in payload_batch:
                tx_body += index.to_bytes(ExtraDataLengths.ITEM_INDEX)
                tx_body += item_type.value.to_bytes(ExtraDataLengths.ITEM_TYPE)
                tx_body += payload.module_id.to_bytes(ExtraDataLengths.MODULE_ID)
                tx_body += len(payload.node_operator_ids).to_bytes(ExtraDataLengths.NODE_OPS_COUNT)
                tx_body += b''.join(
                    no_id.to_bytes(ExtraDataLengths.NODE_OPERATOR_ID)
                    for no_id in payload.node_operator_ids
                )
                tx_body += b''.join(
                    count.to_bytes(ExtraDataLengths.EXITED_VALS_COUNT)
                    for count in payload.vals_counts
                )

                index += 1

            result.append(tx_body)

        return index, result

    @staticmethod
    def add_hashes_to_transactions(txs_data: list[bytes]) -> tuple[bytes, list[bytes]]:
        txs_data.reverse()

        txs_with_hashes = []
        next_hash = ZERO_HASH

        for tx in txs_data:
            full_tx_data = next_hash + tx
            txs_with_hashes.append(full_tx_data)
            next_hash = Web3.keccak(full_tx_data)

        txs_with_hashes.reverse()

        return next_hash, txs_with_hashes
