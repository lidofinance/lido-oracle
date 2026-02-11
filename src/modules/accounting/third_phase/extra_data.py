from dataclasses import dataclass
from itertools import groupby, batched
from typing import Sequence, cast

from src.modules.accounting.third_phase.types import ExtraData, ItemType, ExtraDataLengths, FormatList
from src.modules.submodules.types import ZERO_HASH
from src.types import NodeOperatorGlobalIndex
from src.web3py.types import Web3


@dataclass
class ExitedValidatorsPayload:
    """Payload for EXTRA_DATA_TYPE_EXITED_VALIDATORS (type 2)."""

    module_id: int
    node_operator_ids: Sequence[int]
    vals_counts: Sequence[int]


@dataclass
class OperatorBalancesPayload:
    """Payload for EXTRA_DATA_TYPE_OPERATOR_BALANCES (type 3).
    balances_gwei is the sum of validator balances + pending deposits per operator.
    """

    module_id: int
    node_operator_ids: Sequence[int]
    balances_gwei: Sequence[int]


class ExtraDataService:
    """
    Service that encodes extra data into bytes in correct order.

    Extra data is an array of items, each item being encoded as follows:
    | 32 bytes |  3 bytes  | 2 bytes  |   X bytes   |
    | nextHash | itemIndex | itemType | itemPayload |

    EXTRA_DATA_TYPE_EXITED_VALIDATORS (2) itemPayload format:
    | 3 bytes  |   8 bytes    |  N * 8 bytes      |  N * 16 bytes         |
    | moduleId | nodeOpsCount | nodeOperatorIds   | exitedValidatorsCounts |

    EXTRA_DATA_TYPE_OPERATOR_BALANCES (3) itemPayload format:
    | 3 bytes  |   8 bytes    |  N * 8 bytes    |  N * 16 bytes                       |
    | moduleId | nodeOpsCount | nodeOperatorIds | balances (validator CL + pending)    |

    max_items_count_per_tx - max itemIndex in extra data.
    max_no_in_payload_count - max nodeOpsCount that could be used in itemPayload.
    """

    @classmethod
    def collect(
        cls,
        exited_validators: dict[NodeOperatorGlobalIndex, int],
        max_items_count_per_tx: int,
        max_no_in_payload_count: int,
        operator_balances: dict[NodeOperatorGlobalIndex, int],
    ) -> ExtraData:
        exited_payloads = cls.build_exited_validators_payloads(exited_validators, max_no_in_payload_count)
        balance_payloads = cls.build_operator_balances_payloads(operator_balances, max_no_in_payload_count)

        items_count, txs = cls.build_extra_transactions_data(
            exited_payloads,
            balance_payloads,
            max_items_count_per_tx,
        )
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
    def build_exited_validators_payloads(
        cls,
        validators: dict[NodeOperatorGlobalIndex, int],
        max_no_in_payload_count: int,
    ) -> list[ExitedValidatorsPayload]:
        operator_validators = sorted(validators.items(), key=lambda x: x[0])

        payloads = []

        for module_id, operators_by_module in groupby(operator_validators, key=lambda x: x[0][0]):
            for nos_in_batch in batched(list(operators_by_module), max_no_in_payload_count):
                operator_ids = []
                vals_count = []

                for (_, no_id), validators_count in nos_in_batch:
                    operator_ids.append(no_id)
                    vals_count.append(validators_count)

                payloads.append(
                    ExitedValidatorsPayload(
                        module_id=module_id,
                        node_operator_ids=operator_ids,
                        vals_counts=vals_count,
                    )
                )

        return payloads

    @classmethod
    def build_operator_balances_payloads(
        cls,
        balances: dict[NodeOperatorGlobalIndex, int],
        max_no_in_payload_count: int,
    ) -> list[OperatorBalancesPayload]:
        """Build payloads for EXTRA_DATA_TYPE_OPERATOR_BALANCES.

        Args:
            balances: Dict mapping (module_id, operator_id) to total_balance_gwei
            max_no_in_payload_count: Max operators per payload item
        """
        operator_balances = sorted(balances.items(), key=lambda x: x[0])

        payloads = []

        for module_id, operators_by_module in groupby(operator_balances, key=lambda x: x[0][0]):
            for nos_in_batch in batched(list(operators_by_module), max_no_in_payload_count):
                operator_ids = []
                op_balances = []

                for (_, no_id), balance in nos_in_batch:
                    operator_ids.append(no_id)
                    op_balances.append(balance)

                payloads.append(
                    OperatorBalancesPayload(
                        module_id=module_id,
                        node_operator_ids=operator_ids,
                        balances_gwei=op_balances,
                    )
                )

        return payloads

    @classmethod
    def build_extra_transactions_data(
        cls,
        exited_payloads: list[ExitedValidatorsPayload],
        balance_payloads: list[OperatorBalancesPayload],
        max_items_count_per_tx: int,
    ) -> tuple[int, list[bytes]]:
        # Items sorted by (itemType, moduleId, operatorIds[0])
        # Type 2 (exited) comes before type 3 (balances)
        all_payloads: list[tuple[ItemType, ExitedValidatorsPayload | OperatorBalancesPayload]] = [
            *[(ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS, payload) for payload in exited_payloads],
            *[(ItemType.EXTRA_DATA_TYPE_OPERATOR_BALANCES, payload) for payload in balance_payloads],
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
                    no_id.to_bytes(ExtraDataLengths.NODE_OPERATOR_ID) for no_id in payload.node_operator_ids
                )

                if item_type == ItemType.EXTRA_DATA_TYPE_EXITED_VALIDATORS:
                    payload = cast(ExitedValidatorsPayload, payload)
                    tx_body += b''.join(
                        count.to_bytes(ExtraDataLengths.EXITED_VALS_COUNT) for count in payload.vals_counts
                    )
                elif item_type == ItemType.EXTRA_DATA_TYPE_OPERATOR_BALANCES:
                    payload = cast(OperatorBalancesPayload, payload)
                    tx_body += b''.join(
                        balance.to_bytes(ExtraDataLengths.OPERATOR_BALANCE)
                        for balance in payload.balances_gwei
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
