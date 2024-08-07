import logging
from http import HTTPStatus
from typing import Literal

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BlockHeaderFullResponse, BlockDetailsResponse
from src.providers.http_provider import NotOkResponse
from src.types import SlotNumber, EpochNumber, ReferenceBlockStamp
from src.utils.blockstamp import build_reference_blockstamp, build_blockstamp

logger = logging.getLogger(__name__)


class NoSlotsAvailable(Exception):
    pass


class InconsistentData(Exception):
    pass


class SlotNotFinalized(Exception):
    pass


def _get_closest_non_missed_headers(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
) -> tuple[BlockHeaderFullResponse, BlockHeaderFullResponse]:
    """
    Get past and next closest non-missed slot and returns its headers.

    Raise NoSlotsAvailable if all slots are missed in range [slot, last_finalized_slot_number]
    and we have nowhere to take parent root.
    """
    #  [ ] - slot
    #  [x] - slot with existed block
    #  [o] - slot with missed block
    #
    #  last_finalized = 24
    #  ref_slot = 19
    #
    #                ref_slot           last_finalized
    #                   |                   |
    #                   v                   v
    #   ---[o]-[x]-[x]-[o]-[o]-[o]-[o]-[x]-[x]----> time
    #      16  17  18  19  20  21  22  23  24       slot
    #       -  12  13   -   -   -   -  14  15       block
    #
    #  We have range [19, 24] and we need to find first non-missed slot.
    #
    #  Let's dive into the range circle and consider it in each tick:
    #    1st tick - 19 slot is missed. Check next slot.
    #    2nd tick - 20 slot is missed. Check next slot.
    #    3rd tick - 21 slot is missed. Check next slot.
    #    4th tick - 22 slot is missed. Check next slot.
    #    5th tick - 23 slot exists!
    #               Get `parent_root` of 23 slot and get its parent slot header by this root
    #               In our case it is 18 slot because it's first non-missed slot before 23 slot.
    #
    #  So, in this strategy we always get parent slot of existed slot and can get the nearest slot for `slot`
    #
    #  Exception case can be when all slots are missed in range [slot, last_finalized_slot_number] it will mean that
    #  block response of CL node contradicts itself, because few moments ago we got existed `last_finalized_slot_number`
    if slot > last_finalized_slot_number:
        raise ValueError('`slot` should be less or equal `last_finalized_slot_number`')

    existing_header = None
    for i in range(slot, last_finalized_slot_number + 1):
        try:
            existing_header = cc.get_block_header(SlotNumber(i))
        except NotOkResponse as error:
            if error.status != HTTPStatus.NOT_FOUND:
                # Not expected status - raise exception
                raise error

            logger.warning({'msg': f'Missed slot: {i}. Check next slot.', 'error': str(error.__dict__)})
        else:
            break

    if not existing_header:
        raise NoSlotsAvailable('No slots available for current report. Check your CL node.')

    non_missed_header_parent_root = existing_header.data.header.message.parent_root
    parent_header = cc.get_block_header(non_missed_header_parent_root)

    if (
        int(parent_header.data.header.message.slot) >= slot
        or int(existing_header.data.header.message.slot) - int(parent_header.data.header.message.slot) < 1
    ):
        raise InconsistentData(
            "Parent root next to `slot` existing header doesn't match the expected slot.\n"
            'Probably, a problem with the consensus node.'
        )

    _check_block_header(parent_header)
    _check_block_header(existing_header)
    return parent_header, existing_header


def get_prev_non_missed_slot(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
) -> BlockDetailsResponse:
    parent_header, existing_header = _get_closest_non_missed_headers(cc, slot, last_finalized_slot_number)
    to_get_details = existing_header
    if int(existing_header.data.header.message.slot) - int(parent_header.data.header.message.slot) > 1:
        # there is a gap between parent and existing header (missing slot), so use parent header to get details
        to_get_details = parent_header
    return cc.get_block_details(to_get_details.data.root)


def get_next_non_missed_slot(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
) -> BlockDetailsResponse:
    _, existing_header = _get_closest_non_missed_headers(cc, slot, last_finalized_slot_number)
    return cc.get_block_details(existing_header.data.root)


def get_blockstamp(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
):
    """Get first non-missed slot header and generates blockstamp for it"""
    logger.info({'msg': f'Get Blockstamp for slot: {slot}'})
    existed_slot = get_prev_non_missed_slot(cc, slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {existed_slot.message.slot}'})
    return build_blockstamp(existed_slot)


def get_reference_blockstamp(
    cc: ConsensusClient,
    ref_slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    ref_epoch: EpochNumber,
) -> ReferenceBlockStamp:
    """Get first non-missed slot header and generates reference blockstamp for it"""
    logger.info({'msg': f'Get Reference Blockstamp for ref slot: {ref_slot}'})
    existed_slot = get_prev_non_missed_slot(cc, ref_slot, last_finalized_slot_number)
    logger.info({'msg': f'Resolved to slot: {existed_slot.message.slot}'})
    return build_reference_blockstamp(existed_slot, ref_slot, ref_epoch)


def _check_block_header(block_header: BlockHeaderFullResponse):
    if block_header.finalized is False:
        raise SlotNotFinalized(f'Slot [{block_header.data.header.message.slot}] is not finalized, but should be.')
    if not block_header.data.canonical:
        raise SlotNotFinalized(f'Slot [{block_header.data.header.message.slot}] is not canonical, but should be.')
