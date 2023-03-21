import random
import string
from typing import Callable, Iterable
from unittest.mock import Mock

import pytest

from src.modules.ejector.data_encode import (
    MODULE_ID_LENGTH,
    NODE_OPERATOR_ID_LENGTH,
    VALIDATOR_INDEX_LENGTH,
    VALIDATOR_PUB_KEY_LENGTH,
    encode_data,
)
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    NodeOperatorId,
    StakingModuleId,
)
from tests.factory.no_registry import LidoValidatorFactory

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
        return "0x" + "".join(random.choice(symbols) for _ in range(length))

    return _factory


@pytest.fixture()
def validator_factory(pubkey_factory: Callable[[], str]) -> Callable:
    def _factory(index: int, pubkey: str | None = None):
        v = LidoValidatorFactory.build(index=str(index))
        v.validator.pubkey = pubkey or pubkey_factory()
        return v

    return _factory


@pytest.mark.unit
def test_encode_data(validator_factory: Callable[..., LidoValidator]) -> None:
    data = [
        ((StakingModuleId(42), NodeOperatorId(3)), validator_factory(0)),
        ((StakingModuleId(8), NodeOperatorId(17)), validator_factory(1)),
        ((StakingModuleId(0), NodeOperatorId(0)), validator_factory(2)),
        (
            (
                StakingModuleId(_max_num_fits_bytes(MODULE_ID_LENGTH)),
                NodeOperatorId(_max_num_fits_bytes(NODE_OPERATOR_ID_LENGTH)),
            ),
            validator_factory(_max_num_fits_bytes(VALIDATOR_INDEX_LENGTH)),
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
        assert int.from_bytes(chunks[2]) == int(
            _val.index
        ), "Validator's index mismatch"
        assert chunks[3] == bytes.fromhex(_val.validator.pubkey[2:]), "Pubkey mismatch"


@pytest.mark.unit
def test_encode_data_empty() -> None:
    (result, _) = encode_data([])
    assert len(result) == 0, "Unexpected length of encoded data"


@pytest.mark.unit
def test_encode_data_overflow(validator_factory: Callable[..., LidoValidator]) -> None:
    with pytest.raises(OverflowError):
        encode_data(
            [
                (
                    (
                        StakingModuleId(_max_num_fits_bytes(MODULE_ID_LENGTH) + 1),
                        NodeOperatorId(0),
                    ),
                    validator_factory(0),
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
                    validator_factory(0),
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
                    validator_factory(
                        index=_max_num_fits_bytes(VALIDATOR_INDEX_LENGTH) + 1
                    ),
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
                    validator_factory(0),
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
                    validator_factory(0),
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
                    validator_factory(index=-1),
                )
            ]
        )


@pytest.mark.unit
def test_encode_broken_pubkey(validator_factory: Callable[..., LidoValidator]) -> None:
    with pytest.raises(ValueError, match="Unexpected size of validator pub key"):
        encode_data(
            [
                (
                    (
                        StakingModuleId(0),
                        NodeOperatorId(0),
                    ),
                    validator_factory(index=0, pubkey="0x"),
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
                    validator_factory(
                        index=0,
                        pubkey="0xgggggggggggggggggggggggggggggggggggggggggggggggg",
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
