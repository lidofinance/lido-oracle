import logging
from http import HTTPStatus
from typing import Optional

from src.providers.consensus.client import ConsensusClient
from src.providers.http_provider import NotOkResponse
from src.typings import BlockStamp, SlotNumber, EpochNumber, BlockNumber


logger = logging.getLogger(__name__)


class NoSlotsAvailable(Exception):
    pass


def get_first_non_missed_slot(
    cc: ConsensusClient,
    ref_slot: SlotNumber,
    ref_epoch: Optional[EpochNumber] = None,
) -> BlockStamp:
    """
        Get past closest non-missed slot and generates blockstamp for it.
        Raise NoSlotsAvailable if all slots are missed in max_deep range.
    """
    logger.info({'msg': f'Get Blockstamp for ref slot: {ref_slot}.'})
    for i in range(ref_slot, 1, -1):
        try:
            root = cc.get_block_root(SlotNumber(i)).root
        except NotOkResponse as error:
            if error.status != HTTPStatus.NOT_FOUND:
                # Not expected status - raise exception
                raise error from error

            logger.warning({'msg': f'Missed slot: {i}. Check next slot.', 'error': str(error)})
            continue
        else:
            slot_details = cc.get_block_details(root)

            execution_data = slot_details.message.body['execution_payload']

            return BlockStamp(
                block_root=root,
                slot_number=SlotNumber(int(slot_details.message.slot)),
                state_root=slot_details.message.state_root,
                block_number=BlockNumber(int(execution_data['block_number'])),
                block_hash=execution_data['block_hash'],
                ref_slot=ref_slot,
                ref_epoch=ref_epoch,
            )

    raise NoSlotsAvailable('No slots available for current report.')
