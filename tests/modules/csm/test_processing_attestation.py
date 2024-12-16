from collections import defaultdict
from itertools import chain
from types import SimpleNamespace
from typing import Protocol
from unittest.mock import Mock

import pytest

from src.modules.csm.checkpoint import get_committee_indices, is_electra_attestation, process_attestations
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BlockAttestation
from src.types import BlockStamp
from tests.factory.blockstamp import BlockStampFactory

SLOTS_PER_EPOCH = 32


class Web3(Protocol):
    cc: ConsensusClient


@pytest.fixture()
def blockstamp(request: pytest.FixtureRequest) -> BlockStamp:
    """
    Blockstamp to query CL clients.
    request.param: tuple[StateRoot, SlotNumber]
    """
    state_root, slot_number = request.param
    return BlockStampFactory.build(state_root=state_root, slot_number=slot_number)


@pytest.fixture()
def committees(blockstamp: BlockStamp, web3: Web3):
    committees = {}
    for slot in range(blockstamp.slot_number // SLOTS_PER_EPOCH * SLOTS_PER_EPOCH, blockstamp.slot_number):
        for comm in web3.cc.get_attestation_committees(blockstamp, slot=slot):
            validators = [SimpleNamespace(index=v, included=False) for v in comm.validators]
            committees[(comm.slot, comm.index)] = validators
    return committees


@pytest.mark.parametrize(
    "blockstamp",
    (
        pytest.param(
            ("0x83c9cd854796f8de8283a5e9a51984657cc1832d6f57c6bc4869d9956589cf61", 10267193),
            id="mainnet_10267193",
        ),
    ),
    indirect=True,
)
@pytest.mark.usefixtures("consensus_client")
def test_processing_attestation_before_electra(blockstamp: BlockStamp, web3: Web3, committees: dict):
    atts = web3.cc.get_block_attestations(state_id=blockstamp.slot_number)

    for a in atts:
        assert not is_electra_attestation(a), "Pre-Electra slot with Electra attestation"

    process_attestations(atts, committees)
    included = defaultdict(dict)
    for (slot, _), validators in committees.items():
        for v in validators:
            included[int(slot)][int(v.index)] = v.included

    assert included[10267192][1631491]


@pytest.mark.parametrize(
    "blockstamp",
    (
        pytest.param(
            ("0x3896e71093ed7c41a267e25a43320f622905e1878d97922157ee38851ff3d6b5", 26892),
            id="mekong_26892",
        ),
    ),
    indirect=True,
)
@pytest.mark.usefixtures("consensus_client")
def test_processing_attestation_after_electra(blockstamp: BlockStamp, web3: Web3, committees: dict):
    atts = web3.cc.get_block_attestations(state_id=blockstamp.slot_number)

    for a in atts:
        assert is_electra_attestation(a), "Post-Electra slot with non-Electra attestation"

    process_attestations(atts, committees)
    included = defaultdict(dict)
    for (slot, _), validators in committees.items():
        for v in validators:
            included[int(slot)][int(v.index)] = v.included

    assert all(v is False for v in included[26888].values())  # A missed slot.
    assert not included[26889][43914]
    assert not included[26890][47095]
    assert included[26889][84443]
    assert included[26890][31687]


@pytest.mark.unit
def test_attested_indices_post_electra():
    # Test is based on mekong slot 294664 and attestation for slot 294656.

    committees = {
        ("42", "20"): [Mock(index=20000 + i) for i in range(130)],
        ("42", "22"): [Mock(index=22000 + i) for i in range(131)],
    }
    process_attestations(
        [
            Mock(
                data=Mock(slot="42", index="0"),
                aggregation_bits="0x000000000000000000001000000000000010001000000000000000000000000020",
                committee_bits="0x0000500000000000",
            )
        ],
        committees,  # type: ignore
    )
    vals = [v for v in chain(*committees.values()) if v.included is True]
    assert [v.index for v in vals] == [20084, 22010, 22026]


@pytest.mark.unit
def test_derive_attestation_version():
    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits=None)
    assert not is_electra_attestation(att)

    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits="")
    assert is_electra_attestation(att)


@pytest.mark.unit
def test_get_committee_indices_pre_electra():
    att: BlockAttestation = Mock(
        data=Mock(index="0"),
        aggregation_bits="",
        committee_bits=None,
    )
    assert get_committee_indices(att) == ["0"]

    att: BlockAttestation = Mock(
        data=Mock(index="42"),
        aggregation_bits="",
        committee_bits=None,
    )
    assert get_committee_indices(att) == ["42"]

    att: BlockAttestation = Mock(
        data=Mock(index="42"),
        aggregation_bits="",
        committee_bits="0xff",
    )
    assert get_committee_indices(att) == ["42"]


@pytest.mark.unit
def test_get_committee_indices_post_electra():
    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits="")
    assert get_committee_indices(att) == []

    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits="0x0100000000000000")
    assert get_committee_indices(att) == ["0"]

    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits="0xffffff0000000000")
    assert get_committee_indices(att) == [str(n) for n in range(24)]

    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits="0x0000500000000000")
    assert get_committee_indices(att) == ["20", "22"]

    att: BlockAttestation = Mock(data=Mock(index="0"), aggregation_bits="", committee_bits="0x5ff2990000000000")
    assert get_committee_indices(att) == [
        "0",
        "1",
        "2",
        "3",
        "4",
        "6",
        "9",
        "12",
        "13",
        "14",
        "15",
        "16",
        "19",
        "20",
        "23",
    ]
