from collections import defaultdict
from types import SimpleNamespace
from typing import Protocol

import pytest

from src.modules.csm.checkpoint import is_electra_attestation, process_attestations
from src.providers.consensus.client import ConsensusClient
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
