import random
import string
from typing import Callable, Iterable
from unittest.mock import Mock

import pytest
from eth_typing.encoding import HexStr

from src.modules.ejector.data_encode import (
    MODULE_ID_LENGTH,
    NODE_OPERATOR_ID_LENGTH,
    VALIDATOR_INDEX_LENGTH,
    VALIDATOR_PUB_KEY_LENGTH,
    encode_data,
)
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModuleId

RECORD_LENGTH = sum(
    [
        MODULE_ID_LENGTH,
        NODE_OPERATOR_ID_LENGTH,
        VALIDATOR_INDEX_LENGTH,
        VALIDATOR_PUB_KEY_LENGTH,
    ]
)


@pytest.fixture()
def pubkey_factory() -> Callable:
    def _factory():
        symbols = string.hexdigits
        length = VALIDATOR_PUB_KEY_LENGTH * 2  # 2 hex digits per byte
        return HexStr("0x" + "".join(random.choice(symbols) for _ in range(length)))

    return _factory


@pytest.mark.unit
def test_encode_data(pubkey_factory: Callable[[], HexStr]) -> None:
    def _lido_validator(index: int):
        return Mock(index=index, validator=Mock(pubkey=pubkey_factory()))

    data = [
        ((StakingModuleId(42), NodeOperatorId(3)), _lido_validator(0)),
        ((StakingModuleId(8), NodeOperatorId(17)), _lido_validator(1)),
        ((StakingModuleId(0), NodeOperatorId(0)), _lido_validator(0)),
        (
            (
                StakingModuleId(_max_num_fits_bytes(MODULE_ID_LENGTH)),
                NodeOperatorId(_max_num_fits_bytes(NODE_OPERATOR_ID_LENGTH)),
            ),
            _lido_validator(_max_num_fits_bytes(VALIDATOR_INDEX_LENGTH)),
        ),
    ]

    (result, _) = encode_data(data)
    assert len(result) == len(data) * RECORD_LENGTH, "Unexpected length of encoded data"

    offset = 0
    while offset < len(result):
        record = result[offset : offset + RECORD_LENGTH]
        idx = offset // RECORD_LENGTH
        offset += RECORD_LENGTH

        (_module_id, _nop_id), _val = data[idx]

        chunks = tuple(
            _slice_bytes(
                record,
                MODULE_ID_LENGTH,
                NODE_OPERATOR_ID_LENGTH,
                VALIDATOR_INDEX_LENGTH,
                VALIDATOR_PUB_KEY_LENGTH,
            )
        )

        assert int.from_bytes(chunks[0]) == _module_id, "Module ID mismatch"
        assert int.from_bytes(chunks[1]) == _nop_id, "Node operator ID mismatch"
        assert int.from_bytes(chunks[2]) == _val.index, "Validator's index mismatch"
        assert chunks[3] == bytes.fromhex(_val.validator.pubkey[2:]), "Pubkey mismatch"


@pytest.mark.unit
def test_encode_data_empty() -> None:
    (result, _) = encode_data([])
    assert len(result) == 0, "Unexpected length of encoded data"


@pytest.mark.unit
def test_encode_data_overflow() -> None:
    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(_max_num_fits_bytes(MODULE_ID_LENGTH) + 1),
                        NodeOperatorId(0),
                    ),
                    Mock(index=0),
                )
            ]
        )

    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(
                            _max_num_fits_bytes(NODE_OPERATOR_ID_LENGTH) + 1
                        ),
                    ),
                    Mock(index=0),
                )
            ]
        )

    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(0),
                    ),
                    Mock(index=_max_num_fits_bytes(VALIDATOR_INDEX_LENGTH) + 1),
                )
            ]
        )

    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(-1),
                        NodeOperatorId(0),
                    ),
                    Mock(index=0),
                )
            ]
        )

    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(-1),
                    ),
                    Mock(index=0),
                )
            ]
        )

    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(0),
                    ),
                    Mock(index=-1),
                )
            ]
        )


@pytest.mark.unit
def test_encode_broken_pubkey() -> None:
    with pytest.raises(ValueError, match="Unexpected size of validator pub key"):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(0),
                    ),
                    Mock(index=0, validator=Mock(pubkey="0x")),
                )
            ]
        )

    with pytest.raises(ValueError, match="non-hexadecimal number found"):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(0),
                    ),
                    Mock(
                        index=0,
                        validator=Mock(
                            pubkey="0xgggggggggggggggggggggggggggggggggggggggggggggggg"
                        ),
                    ),
                )
            ]
        )


def _max_num_fits_bytes(num_bytes: int) -> int:
    """
    >>> _max_num_fits_bytes(1)
    255
    """
    if num_bytes < 0:
        raise ValueError("_max_num_fits_bytes: num_bytes must be positive")
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
