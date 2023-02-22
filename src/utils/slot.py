import logging
from http import HTTPStatus
from typing import Optional

from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.typings import BlockHeaderFullResponse
from src.providers.http_provider import NotOkResponse
from src.typings import BlockStamp, SlotNumber, EpochNumber, BlockNumber


logger = logging.getLogger(__name__)


class NoSlotsAvailable(Exception):
    pass


def get_first_non_missed_slot(
    cc: ConsensusClient,
    ref_slot: SlotNumber,
    last_finalized_slot_number: SlotNumber,
    ref_epoch: Optional[EpochNumber] = None,
) -> BlockStamp:
    """
        Get past closest non-missed slot and generates blockstamp for it.
        Raise NoSlotsAvailable if all slots are missed in max_deep range.
    """
    if ref_slot > last_finalized_slot_number:
        raise ValueError('ref_slot should be less or equal to last finalized slot_number ')

    logger.info({'msg': f'Get Blockstamp for ref slot: {ref_slot}.'})
    ref_slot_is_missed = False
    next_existed_header = None
    for i in range(ref_slot, last_finalized_slot_number + 1):
        try:
            next_existed_header = cc.get_block_header(SlotNumber(i))
            break
        except NotOkResponse as error:
            if error.status != HTTPStatus.NOT_FOUND:
                # Not expected status - raise exception
                raise error from error

            ref_slot_is_missed = True

            logger.warning({'msg': f'Missed slot: {i}. Check next slot.', 'error': str(error)})
            continue

    if not ref_slot_is_missed and next_existed_header:
        # Ref slot is not missed. Just get its details by root

        return _build_blockstamp(cc, next_existed_header, ref_slot, ref_epoch)

    if ref_slot_is_missed and next_existed_header:
        # Ref slot is missed, and we have next non-missed slot.
        # We should get parent root of this non-missed slot
        # and get details of its parent slot until we found slot < ref_slot.

        not_missed_header_slot = int(next_existed_header.data.header.message.slot)
        not_missed_header_parent_root = next_existed_header.data.header.message.parent_root
        while not_missed_header_slot > ref_slot:
            next_existed_header = cc.get_block_header(not_missed_header_parent_root)
            not_missed_header_slot = int(next_existed_header.data.header.message.slot)
            not_missed_header_parent_root = next_existed_header.data.header.message.parent_root

        return _build_blockstamp(cc, next_existed_header, ref_slot, ref_epoch)

    if ref_slot_is_missed and not next_existed_header:
        raise NoSlotsAvailable('No slots available for current report. Check your CL node.')


def _build_blockstamp(
    cc: ConsensusClient,
    header: BlockHeaderFullResponse,
    ref_slot: SlotNumber,
    ref_epoch: Optional[EpochNumber] = None,
):
    slot_details = cc.get_block_details(header.data.root)

    execution_data = slot_details.message.body['execution_payload']

    return BlockStamp(
        block_root=header.data.root,
        slot_number=SlotNumber(int(slot_details.message.slot)),
        state_root=slot_details.message.state_root,
        block_number=BlockNumber(int(execution_data['block_number'])),
        block_hash=execution_data['block_hash'],
        block_timestamp=int(execution_data['timestamp']),
        ref_slot=ref_slot,
        ref_epoch=ref_epoch,
    )
