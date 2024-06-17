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


def get_first_non_missed_slot(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    direction: Literal['back'] | Literal['forward'] = 'back'
) -> BlockDetailsResponse:
    """
    Get past/next closest non-missed slot and returns its details.

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
    #               If we seek for the next non-missed slot, we're finished. Otherwise,
    #               get `parent_root` of 23 slot and get its parent slot by this root
    #               In our case it is 18 slot because it's first non-missed slot before 23 slot.
    #
    #  So, in this strategy we always get parent slot of existed slot and can get the nearest slot for `ref_slot`
    #
    #  Exception case can be when all slots are missed in range [ref_slot, last_finalized_slot_number] it will mean that
    #  block response of CL node contradicts itself, because few moments ago we got existed `last_finalized_slot_number`

    if slot > last_finalized_slot_number:
        raise ValueError('ref_slot should be less or equal to the last finalized slot_number.')

    logger.info({'msg': f'Get Blockstamp for ref slot: {slot}.'})

    ref_slot_is_missing = False
    existing_header = None
    for i in range(slot, last_finalized_slot_number + 1):
        try:
            existing_header = cc.get_block_header(SlotNumber(i))
        except NotOkResponse as error:
            if error.status != HTTPStatus.NOT_FOUND:
                # Not expected status - raise exception
                raise error

            ref_slot_is_missing = True

            logger.warning({'msg': f'Missed slot: {i}. Check next slot.', 'error': str(error.__dict__)})
        else:
            break

    if not existing_header:
        raise NoSlotsAvailable('No slots available for current report. Check your CL node.')

    if ref_slot_is_missing:
        # Ref slot is missing. We need to check the parent root found non-missing slot
        non_missed_header_parent_root = existing_header.data.header.message.parent_root
        parent_header = cc.get_block_header(non_missed_header_parent_root)

        if int(parent_header.data.header.message.slot) >= slot:
            raise InconsistentData(
                "Parent root next to the ref slot's existing header doesn't match the expected slot.\n"
                'Probably, a problem with the consensus node.'
            )

        if direction == 'back':
            _check_block_header(existing_header)
            existing_header = parent_header

    _check_block_header(existing_header)
    slot_details = cc.get_block_details(existing_header.data.root)
    logger.info({'msg': f'Resolved to slot: {slot_details.message.slot}'})
    return slot_details


def get_blockstamp(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
):
    """Get first non-missed slot header and generates blockstamp for it"""
    existed_slot = get_first_non_missed_slot(cc, slot, last_finalized_slot_number)
    return build_blockstamp(existed_slot)


def get_reference_blockstamp(
    cc: ConsensusClient,
    ref_slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    ref_epoch: EpochNumber,
) -> ReferenceBlockStamp:
    """Get first non-missed slot header and generates reference blockstamp for it"""
    existed_slot = get_first_non_missed_slot(cc, ref_slot, last_finalized_slot_number)
    return build_reference_blockstamp(existed_slot, ref_slot, ref_epoch)


def _check_block_header(block_header: BlockHeaderFullResponse):
    if block_header.finalized is False:
        raise SlotNotFinalized(f'Slot [{block_header.data.header.message.slot}] is not finalized, but should be.')
    if not block_header.data.canonical:
        raise SlotNotFinalized(f'Slot [{block_header.data.header.message.slot}] is not canonical, but should be.')
