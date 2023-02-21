# ------ Get first non missed slot ------------
from http import HTTPStatus
from unittest.mock import Mock

import pytest

from src.providers.http_provider import NotOkResponse
from src.typings import BlockStamp
from src.utils.slot import NoSlotsAvailable, get_first_non_missed_slot
from tests.conftest import get_blockstamp_by_state


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_first_non_missed_slot(web3, consensus_client):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')

    blockstamp = get_first_non_missed_slot(
        web3.cc,
        ref_slot=latest_blockstamp.slot_number,
        ref_epoch=latest_blockstamp.slot_number//32,
    )

    assert blockstamp.slot_number == latest_blockstamp.slot_number
    assert blockstamp.ref_epoch == latest_blockstamp.slot_number//32


@pytest.mark.unit
@pytest.mark.possible_integration
def test_get_third_non_missed_slot(web3, consensus_client):
    def get_block_root(_):
        setattr(get_block_root, "call_count", getattr(get_block_root, "call_count", 0) + 1)
        if getattr(get_block_root, "call_count") == 3:
            web3.cc.get_block_root = original
        raise NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text")

    latest_blockstamp = get_blockstamp_by_state(web3, 'head')

    original = web3.cc.get_block_root
    web3.cc.get_block_root = Mock(side_effect=get_block_root)
    blockstamp = get_first_non_missed_slot(
        web3.cc,
        ref_slot=139456,
        ref_epoch=139456//32,
    )
    assert isinstance(blockstamp, BlockStamp)
    assert blockstamp.slot_number < latest_blockstamp.slot_number


@pytest.mark.unit
@pytest.mark.possible_integration
def test_all_slots_are_missed(web3, consensus_client):
    latest_blockstamp = get_blockstamp_by_state(web3, 'head')
    web3.cc.get_block_root = Mock(side_effect=NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text"))
    with pytest.raises(NoSlotsAvailable):
        get_first_non_missed_slot(web3.cc, latest_blockstamp.ref_slot)
