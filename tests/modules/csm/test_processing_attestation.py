from itertools import chain
from unittest.mock import Mock

import pytest

from src.modules.csm.checkpoint import (
    get_committee_indices,
    hex_bitlist_to_list,
    hex_bitvector_to_list,
    process_attestations,
)
from src.providers.consensus.types import BlockAttestation


@pytest.mark.unit
def test_hex_bitvector_to_list():
    bits = hex_bitvector_to_list("0x00")
    assert bits == [False] * 8

    bits = hex_bitvector_to_list("00")
    assert bits == [False] * 8

    bits = hex_bitvector_to_list("50")
    assert bits == [
        # 0
        False,
        False,
        False,
        False,
        # 5 little-endian
        True,
        False,
        True,
        False,
    ]

    bits = hex_bitvector_to_list("0x3174")
    assert bits == [
        # 1 little-endian
        True,
        False,
        False,
        False,
        # 3 little-endian
        True,
        True,
        False,
        False,
        # 4 little-endian
        False,
        False,
        True,
        False,
        # 7 little-endian
        True,
        True,
        True,
        False,
    ]


@pytest.mark.unit
def test_hex_bitlist_to_list():
    bits = hex_bitlist_to_list("0x000000000000000000001000000000000010001000000000000000000000000020")
    assert len(bits) == 261
    assert [i for (i, v) in enumerate(bits) if v] == [84, 140, 156]

    with pytest.raises(ValueError, match="invalid bitlist"):
        hex_bitlist_to_list("0x000000000000000000001000000000000010001000000000000000000000000000")

    bits = hex_bitlist_to_list("0x01")
    assert bits == []


@pytest.mark.unit
def test_attested_indices():
    committees = {
        (42, 20): [Mock(index=20000 + i) for i in range(130)],
        (42, 22): [Mock(index=22000 + i) for i in range(131)],
        (17, 12): [Mock(index=12000 + i) for i in range(999)],
    }
    process_attestations(
        [
            Mock(
                data=Mock(slot=42, index=0),
                aggregation_bits="0x000000000000000000001000000000000010001000000000000000000000000020",
                committee_bits="0x0000500000000000",
            ),
            Mock(
                data=Mock(slot=17, index=0),
                aggregation_bits="0x0000000000000000000030",
                committee_bits="0x0010",
            ),
        ],
        committees,  # type: ignore
    )
    vals = [v for v in chain(*committees.values()) if v.included is True]
    assert [v.index for v in vals] == [20084, 22010, 22026, 12084]


@pytest.mark.unit
def test_get_committee_indices():
    att: BlockAttestation = Mock(data=Mock(index=0), aggregation_bits="", committee_bits="")
    assert get_committee_indices(att) == []

    att: BlockAttestation = Mock(data=Mock(index=0), aggregation_bits="", committee_bits="0x0000000000000000")
    assert get_committee_indices(att) == []

    att: BlockAttestation = Mock(data=Mock(index=0), aggregation_bits="", committee_bits="0x0100000000000000")
    assert get_committee_indices(att) == [0]

    att: BlockAttestation = Mock(data=Mock(index=0), aggregation_bits="", committee_bits="0xffffff0000000000")
    assert get_committee_indices(att) == [n for n in range(24)]

    att: BlockAttestation = Mock(data=Mock(index=0), aggregation_bits="", committee_bits="0x0000500000000000")
    assert get_committee_indices(att) == [20, 22]

    att: BlockAttestation = Mock(data=Mock(index=0), aggregation_bits="", committee_bits="0x5ff2990000000000")
    assert get_committee_indices(att) == [
        0,
        1,
        2,
        3,
        4,
        6,
        9,
        12,
        13,
        14,
        15,
        16,
        19,
        20,
        23,
    ]
