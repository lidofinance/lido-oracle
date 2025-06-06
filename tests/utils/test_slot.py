from http import HTTPStatus
from unittest.mock import Mock

import pytest

from src.providers.http_provider import NotOkResponse
from src.types import SlotNumber
from src.utils.slot import NoSlotsAvailable, get_prev_non_missed_slot, get_non_missed_slot_header
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import BlockDetailsResponseFactory
from tests.factory.consensus import BlockHeaderFullResponseFactory


@pytest.mark.unit
def test_get_first_non_missed_slot(web3):
    finalized_blockstamp = ReferenceBlockStampFactory.build(slot_number=294271)
    ref_slot = SlotNumber(finalized_blockstamp.slot_number - 225)
    web3.cc.get_block_header.return_value = BlockHeaderFullResponseFactory.build(
        data={
            "header": {
                "message": {
                    "slot": ref_slot,
                },
            }
        }
    )
    web3.cc.get_block_details.return_value = BlockDetailsResponseFactory.build(
        message={
            "slot": ref_slot,
        }
    )

    slot_details = get_prev_non_missed_slot(
        web3.cc,
        slot=ref_slot,
        last_finalized_slot_number=finalized_blockstamp.slot_number,
    )

    assert slot_details.message.slot == ref_slot


@pytest.mark.unit
def test_all_slots_are_missed(web3):
    blockstamp = ReferenceBlockStampFactory.build()
    web3.cc.get_block_header = Mock(side_effect=NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text"))

    with pytest.raises(NoSlotsAvailable):
        get_prev_non_missed_slot(
            cc=web3.cc,
            slot=blockstamp.ref_slot,
            last_finalized_slot_number=SlotNumber(blockstamp.ref_slot + 50),
        )


@pytest.mark.unit
def test_get_third_non_missed_slot_backward(web3):
    ref_slot = SlotNumber(139457)
    finalized_blockstamp = ReferenceBlockStampFactory.build(slot_number=ref_slot + 10)

    missed_slots_count = 3
    first_non_missed_slot = ref_slot + missed_slots_count

    parent_slot = SlotNumber(139455)

    # Mock get_block_header to fail twice, succeed on the third call with first_non_missed_slot
    # then return parent_slot for the fourth call to get parent_header of first_non_missed_slot
    def get_block_header(state_id):
        setattr(get_block_header, "call_count", getattr(get_block_header, "call_count", 0) + 1)
        if getattr(get_block_header, "call_count") < missed_slots_count:
            raise NotOkResponse("No slots", status=HTTPStatus.NOT_FOUND, text="text")
        elif getattr(get_block_header, "call_count") == missed_slots_count:
            return BlockHeaderFullResponseFactory.build(
                data={
                    "header": {
                        "message": {
                            "slot": first_non_missed_slot,
                        },
                    },
                }
            )
        else:
            return BlockHeaderFullResponseFactory.build(
                data={
                    "header": {
                        "message": {
                            "slot": parent_slot,
                        },
                    },
                }
            )

    web3.cc.get_block_header = Mock(side_effect=get_block_header)
    web3.cc.get_block_details = Mock(return_value=BlockDetailsResponseFactory.build(message={"slot": parent_slot}))

    slot_details = get_prev_non_missed_slot(
        web3.cc,
        slot=ref_slot,
        last_finalized_slot_number=finalized_blockstamp.slot_number,
    )

    assert slot_details.message.slot < finalized_blockstamp.slot_number
    assert slot_details.message.slot == parent_slot
