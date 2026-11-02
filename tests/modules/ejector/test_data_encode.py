from collections.abc import Iterable

import pytest

from src.modules.oracles.ejector.data_encode import (
    AMOUNT_LENGTH,
    FWR_AMOUNT,
    KEY_INDEX_LENGTH,
    MAX_PWR_AMOUNT,
    MAX_REQUESTS_PER_REPORT,
    MODULE_ID_LENGTH,
    NODE_OPERATOR_ID_LENGTH,
    RECORD_LENGTH,
    InvalidWithdrawalRequestsError,
    WithdrawalRequest,
    encode_data,
)
from src.types import Gwei, NodeOperatorId, StakingModuleId


def _request(module_id: int = 1, node_operator_id: int = 0, key_index: int = 0, amount: int = 0) -> WithdrawalRequest:
    return WithdrawalRequest(
        module_id=StakingModuleId(module_id),
        node_operator_id=NodeOperatorId(node_operator_id),
        key_index=key_index,
        amount=Gwei(amount),
    )


def _max_num_fits_bytes(num_bytes: int) -> int:
    """
    >>> _max_num_fits_bytes(1)
    255
    """
    return (2**8) ** num_bytes - 1


def _slice_bytes(data: bytes, *segs: int) -> Iterable[bytes]:
    """
    >>> list(_slice_bytes(b"1234567890", 2, 3, 5))
    [b'12', b'345', b'67890']
    """
    offset = 0
    for seg in segs:
        yield data[offset : offset + seg]
        offset += seg
    assert offset == len(data), "Unexpected length of data"


def _decode(data: bytes) -> list[tuple[int, int, int, int]]:
    assert len(data) % RECORD_LENGTH == 0, "Unexpected length of encoded data"
    records = []
    for offset in range(0, len(data), RECORD_LENGTH):
        chunks = _slice_bytes(
            data[offset : offset + RECORD_LENGTH],
            MODULE_ID_LENGTH,
            NODE_OPERATOR_ID_LENGTH,
            KEY_INDEX_LENGTH,
            AMOUNT_LENGTH,
        )
        records.append(tuple(int.from_bytes(c) for c in chunks))
    return records


@pytest.mark.unit
def test_record_length_is_24_bytes() -> None:
    assert RECORD_LENGTH == 24


@pytest.mark.unit
def test_encode_data_layout() -> None:
    requests = [
        _request(module_id=1, node_operator_id=2, key_index=3, amount=0),
        _request(module_id=4, node_operator_id=5, key_index=6, amount=32 * 10**9),
        _request(
            module_id=_max_num_fits_bytes(MODULE_ID_LENGTH),
            node_operator_id=_max_num_fits_bytes(NODE_OPERATOR_ID_LENGTH),
            key_index=_max_num_fits_bytes(KEY_INDEX_LENGTH),
            amount=MAX_PWR_AMOUNT,
        ),
    ]

    decoded = _decode(encode_data(requests))

    assert decoded == [(r.module_id, r.node_operator_id, r.key_index, r.amount) for r in requests]


@pytest.mark.unit
def test_encode_data_known_bytes() -> None:
    # Fixed vector so a layout change cannot pass unnoticed: moduleId=1, nodeOpId=2, keyIndex=3, amount=1 ETH.
    data = encode_data([_request(module_id=1, node_operator_id=2, key_index=3, amount=10**9)])

    assert data.hex() == '000001' + '0000000002' + '0000000000000003' + '000000003b9aca00'


@pytest.mark.unit
def test_encode_data_keeps_input_order() -> None:
    # Report order is the FIFO execution order on-chain, so the encoder must not sort.
    requests = [
        _request(module_id=3, node_operator_id=9, key_index=50),
        _request(module_id=1, node_operator_id=0, key_index=7, amount=10**9),
        _request(module_id=2, node_operator_id=5, key_index=1),
    ]

    decoded = _decode(encode_data(requests))

    assert [d[0] for d in decoded] == [3, 1, 2]


@pytest.mark.unit
def test_encode_data_empty() -> None:
    assert encode_data([]) == b''


@pytest.mark.unit
def test_fwr_is_zero_amount() -> None:
    assert _request(amount=FWR_AMOUNT).is_full
    assert not _request(amount=1).is_full


@pytest.mark.unit
def test_encode_data_max_requests() -> None:
    requests = [_request(key_index=i) for i in range(MAX_REQUESTS_PER_REPORT)]

    assert len(encode_data(requests)) == MAX_REQUESTS_PER_REPORT * RECORD_LENGTH

    with pytest.raises(InvalidWithdrawalRequestsError, match='Too many requests'):
        encode_data([*requests, _request(key_index=MAX_REQUESTS_PER_REPORT)])


@pytest.mark.unit
@pytest.mark.parametrize('second_amount', [0, 10**9])
def test_encode_data_rejects_duplicate_validator(second_amount: int) -> None:
    with pytest.raises(InvalidWithdrawalRequestsError, match='Duplicate request'):
        encode_data(
            [
                _request(module_id=1, node_operator_id=2, key_index=3, amount=10**9),
                _request(module_id=1, node_operator_id=2, key_index=3, amount=second_amount),
            ]
        )


@pytest.mark.unit
def test_encode_data_same_key_index_in_other_operator_is_not_duplicate() -> None:
    # Key indexes are per operator, so the same index under another operator is another validator.
    encode_data([_request(node_operator_id=1, key_index=0), _request(node_operator_id=2, key_index=0)])


@pytest.mark.unit
def test_encode_data_rejects_pwr_above_max() -> None:
    encode_data([_request(amount=MAX_PWR_AMOUNT)])

    with pytest.raises(InvalidWithdrawalRequestsError, match='exceeds MAX_PWR_AMOUNT'):
        encode_data([_request(amount=MAX_PWR_AMOUNT + 1)])


@pytest.mark.unit
def test_max_pwr_amount_is_2016_eth() -> None:
    assert MAX_PWR_AMOUNT == 2016 * 10**9


@pytest.mark.unit
@pytest.mark.parametrize(
    'kwargs',
    [
        {'module_id': _max_num_fits_bytes(MODULE_ID_LENGTH) + 1},
        {'node_operator_id': _max_num_fits_bytes(NODE_OPERATOR_ID_LENGTH) + 1},
        {'key_index': _max_num_fits_bytes(KEY_INDEX_LENGTH) + 1},
        {'module_id': -1},
        {'node_operator_id': -1},
        {'key_index': -1},
        {'amount': -1},
    ],
)
def test_encode_data_overflow(kwargs: dict) -> None:
    with pytest.raises(OverflowError):
        encode_data([_request(**kwargs)])
