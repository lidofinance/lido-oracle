import logging
from http import HTTPStatus

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import BlockDetailsResponse, BlockHeaderFullResponse
from src.providers.execution.exceptions import InconsistentData
from src.providers.http_provider import NotOkResponse
from src.types import EpochNumber, ReferenceBlockStamp, SlotNumber
from src.utils.blockstamp import build_blockstamp, build_reference_blockstamp

logger = logging.getLogger(__name__)


class NoSlotsAvailable(Exception):
    pass


class SlotNotFinalized(Exception):
    pass


def get_non_missed_slot_header(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
) -> tuple[bool, BlockHeaderFullResponse]:
    """
    Get non-missed slot header near to `slot` in range [slot, last_finalized_slot_number].

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
    #               Get slot data of 23 slot.
    #
    #  So, in this strategy we always get parent slot of existed slot and can get the nearest slot for `slot`
    #
    #  Exception case can be when all slots are missed in range [slot, last_finalized_slot_number] it will mean that
    #  block response of CL node contradicts itself, because few moments ago we got existed `last_finalized_slot_number`
    if slot > last_finalized_slot_number:
        raise ValueError(f'{slot=} should be less or equal {last_finalized_slot_number=}')

    slot_is_missing = False
    existing_header = None
    for i in range(slot, last_finalized_slot_number + 1):
        try:
            existing_header = cc.get_block_header(SlotNumber(i))
        except NotOkResponse as error:
            if error.status != HTTPStatus.NOT_FOUND:
                # Not expected status - raise exception
                raise error

            slot_is_missing = True

            logger.warning({'msg': f'Missed slot: {i}. Check next slot.', 'error': str(error.__dict__)})
        else:
            break

    if not existing_header:
        raise NoSlotsAvailable('No slots available for current report. Check your CL node.')

    _check_block_header(existing_header)
    return slot_is_missing, existing_header


def get_prev_non_missed_slot(
    cc: ConsensusClient,
    slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
) -> BlockDetailsResponse:
    """
    Get non-missed slot data. In case of missed slot, we take parent root and get parent slot data.
    """
    is_slot_missing, existing_header = get_non_missed_slot_header(cc, slot, last_finalized_slot_number)

    if not is_slot_missing:
        return cc.get_block_details(existing_header.data.root)

    non_missed_header_parent_root = existing_header.data.header.message.parent_root
    parent_header = cc.get_block_header(non_missed_header_parent_root)

    if (
        parent_header.data.header.message.slot >= slot
        or existing_header.data.header.message.slot - parent_header.data.header.message.slot < 1
    ):
        raise InconsistentData(
            "Parent root next to `slot` existing header doesn't match the expected slot.\n"
            f'Expected {slot=}, Got {parent_header.data.header.message.slot=}'
            'Probably, a problem with the consensus node.'
        )

    _check_block_header(parent_header)
    return cc.get_block_details(parent_header.data.root)


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
