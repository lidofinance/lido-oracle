import pytest
from web3 import Web3

from src.modules.accounting.third_phase.extra_data import (
    ExtraDataService,
    ExitedValidatorsPayload,
    OperatorBalancesPayload,
)
from src.modules.accounting.third_phase.types import FormatList
from src.modules.submodules.types import ZERO_HASH


@pytest.mark.unit
def test_collect():
    extra_data = ExtraDataService.collect(
        {
            (1, 2): 16,
            (2, 1): 12,
            (2, 2): 14,
            (2, 3): 18,
            (2, 5): 18,
            (2, 6): 18,
            (2, 7): 18,
            (2, 8): 18,
            (3, 1): 18,
        },
        2,
        3,
        operator_balances={},
    )

    assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
    assert len(extra_data.extra_data_list) == 3
    assert extra_data.data_hash == Web3.keccak(extra_data.extra_data_list[0])
    assert extra_data.extra_data_list[0][:32] == Web3.keccak(extra_data.extra_data_list[1])
    assert (
        extra_data.extra_data_list[0]
        == b'\xad\x7f\xa4"\r\x8b\xe8\xbc\xb4H`\x00+n\n\x87w\xa6\x03\xbc\xbd\xda\xee\xfe\xc2J\xdd\xdf\xcd\xbc\x023\x00\x00\x00\x00\x02\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x01\x00\x02\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0c\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x12'
    )

    extra_data = ExtraDataService.collect({}, 2, 4, operator_balances={})
    assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_EMPTY.value


@pytest.mark.unit
def test_build_exited_validators_payloads():
    vals_payloads = {
        (1, 1): 1,
        (1, 2): 2,
        (1, 3): 3,
        (1, 4): 4,
        (1, 5): 5,
        (2, 1): 6,
        (2, 2): 7,
    }

    result = ExtraDataService.build_exited_validators_payloads(
        vals_payloads,
        2,
    )

    assert len(result) == 4

    assert result[0].module_id == 1
    assert result[1].module_id == 1
    assert result[1].node_operator_ids == [3, 4]
    assert result[1].vals_counts == [3, 4]
    assert result[2].module_id == 1
    assert result[2].node_operator_ids == [5]
    assert result[2].vals_counts == [5]
    assert result[3].module_id == 2

    assert not ExtraDataService.build_exited_validators_payloads({}, 2)


@pytest.mark.unit
def test_build_extra_transactions_data():
    exit_items = [
        ExitedValidatorsPayload(
            1,
            [1, 2, 3],
            [11, 22, 33],
        ),
        ExitedValidatorsPayload(
            2,
            [1, 2, 3],
            [11, 22, 33],
        ),
    ]

    items_count, txs = ExtraDataService.build_extra_transactions_data(
        exit_items,
        [],
        2,
    )

    assert items_count == 2
    assert len(txs[0]) == 176
    assert (
        txs[0]
        == b'\x00\x00\x00\x00\x02\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x16\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00!\x00\x00\x01\x00\x02\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x0b\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x16\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00!'
    )


@pytest.mark.unit
def test_add_hashes_to_transactions():
    next_hash, txs = ExtraDataService.add_hashes_to_transactions([])

    assert next_hash == ZERO_HASH
    assert txs == []

    transactions = [b'a' * 32, b'b' * 32, b'c' * 32]
    next_hash, txs = ExtraDataService.add_hashes_to_transactions(transactions)

    assert txs[0][32:] == b'a' * 32
    assert txs[1][32:] == b'b' * 32
    assert txs[2][32:] == b'c' * 32

    assert next_hash == Web3.keccak(Web3.keccak(Web3.keccak(ZERO_HASH + b'c' * 32) + b'b' * 32) + b'a' * 32)
    assert txs[0][:32] == Web3.keccak(Web3.keccak(ZERO_HASH + b'c' * 32) + b'b' * 32)
    assert txs[1][:32] == Web3.keccak(ZERO_HASH + b'c' * 32)
    assert txs[2][:32] == ZERO_HASH


@pytest.mark.unit
def test_build_operator_balances_payloads():
    balances = {
        (1, 1): (100, 10),
        (1, 2): (200, 20),
        (1, 3): (300, 30),
        (2, 1): (400, 40),
        (2, 2): (500, 50),
    }

    result = ExtraDataService.build_operator_balances_payloads(balances, 2)

    assert len(result) == 3

    assert result[0].module_id == 1
    assert result[0].node_operator_ids == [1, 2]
    assert result[0].validator_balances_gwei == [100, 200]
    assert result[0].pending_balances_gwei == [10, 20]

    assert result[1].module_id == 1
    assert result[1].node_operator_ids == [3]
    assert result[1].validator_balances_gwei == [300]
    assert result[1].pending_balances_gwei == [30]

    assert result[2].module_id == 2
    assert result[2].node_operator_ids == [1, 2]
    assert result[2].validator_balances_gwei == [400, 500]
    assert result[2].pending_balances_gwei == [40, 50]

    assert not ExtraDataService.build_operator_balances_payloads({}, 2)


@pytest.mark.unit
def test_build_extra_transactions_data_with_operator_balances():
    balance_items = [
        OperatorBalancesPayload(
            module_id=1,
            node_operator_ids=[1, 2],
            validator_balances_gwei=[100, 200],
            pending_balances_gwei=[10, 20],
        ),
    ]

    items_count, txs = ExtraDataService.build_extra_transactions_data(
        [],
        balance_items,
        2,
    )

    assert items_count == 1
    assert len(txs[0]) == 96


@pytest.mark.unit
def test_collect_with_operator_balances():
    extra_data = ExtraDataService.collect(
        exited_validators={(1, 1): 5},
        max_items_count_per_tx=10,
        max_no_in_payload_count=10,
        operator_balances={(2, 1): (1000, 100)},
    )

    assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
    assert extra_data.items_count == 2


@pytest.mark.unit
def test_collect_only_operator_balances():
    extra_data = ExtraDataService.collect(
        exited_validators={},
        max_items_count_per_tx=10,
        max_no_in_payload_count=10,
        operator_balances={
            (1, 0): (32_000_000_000, 0),
            (1, 1): (31_500_000_000, 1_000_000_000),
        },
    )

    assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
    assert extra_data.items_count == 1


@pytest.mark.unit
def test_collect_operator_balances_ordering():
    extra_data = ExtraDataService.collect(
        exited_validators={(1, 0): 5, (2, 0): 3},
        max_items_count_per_tx=100,
        max_no_in_payload_count=100,
        operator_balances={(1, 0): (32_000_000_000, 0), (2, 0): (33_000_000_000, 500_000_000)},
    )

    assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
    assert extra_data.items_count == 4

    tx_data = extra_data.extra_data_list[0]
    raw = tx_data[32:]

    item_index = int.from_bytes(raw[0:3])
    item_type = int.from_bytes(raw[3:5])
    assert item_index == 0
    assert item_type == 2


@pytest.mark.unit
def test_collect_operator_balances_batching():
    extra_data = ExtraDataService.collect(
        exited_validators={},
        max_items_count_per_tx=100,
        max_no_in_payload_count=2,
        operator_balances={
            (1, 0): (100, 10),
            (1, 1): (200, 20),
            (1, 2): (300, 30),
        },
    )

    assert extra_data.format == FormatList.EXTRA_DATA_FORMAT_LIST_NON_EMPTY.value
    assert extra_data.items_count == 2
