# ------ Get first non missed slot ------------
from http import HTTPStatus
from unittest.mock import Mock

import pytest

from src.providers.http_provider import NotOkResponse
from src.utils.slot import NoSlotsAvailable, get_first_non_missed_slot
from tests.conftest import get_blockstamp_by_state


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_first_non_missed_slot(web3, consensus_client):
    finalized_blockstamp = get_blockstamp_by_state(web3, 'finalized')
    ref_slot = finalized_blockstamp.slot_number - 225

    slot_details = get_first_non_missed_slot(
        web3.cc,
        slot=ref_slot,
        last_finalized_slot_number=finalized_blockstamp.slot_number,
    )

    assert int(slot_details.message.slot) == ref_slot


@pytest.mark.unit
def test_get_third_non_missed_slot(web3, consensus_client):
    def get_block_header(_):
        setattr(get_block_header, "call_count", getattr(get_block_header, "call_count", 0) + 1)
        if getattr(get_block_header, "call_count") == 3:
            web3.cc.get_block_header = original
        raise NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text")

    finalized_blockstamp = get_blockstamp_by_state(web3, 'finalized')

    original = web3.cc.get_block_header
    web3.cc.get_block_header = Mock(side_effect=get_block_header)
    slot_details = get_first_non_missed_slot(
        web3.cc,
        slot=139456,
        last_finalized_slot_number=finalized_blockstamp.slot_number,
    )
    assert int(slot_details.message.slot) < finalized_blockstamp.slot_number
    assert int(slot_details.message.slot) == 139455


@pytest.mark.unit
@pytest.mark.possible_integration
def test_all_slots_are_missed(web3, consensus_client):
    finalized_blockstamp = get_blockstamp_by_state(web3, 'finalized')
    web3.cc.get_block_header = Mock(side_effect=NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text"))
    with pytest.raises(NoSlotsAvailable):
        get_first_non_missed_slot(
            cc=web3.cc,
            slot=finalized_blockstamp.ref_slot,
            last_finalized_slot_number=finalized_blockstamp.ref_slot + 50,
        )
