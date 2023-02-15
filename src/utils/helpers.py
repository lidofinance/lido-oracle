import logging
from src.providers.consensus.client import ConsensusClient
from src.providers.http_provider import NotOkResponse
from src.typings import BlockStamp, SlotNumber

logger = logging.getLogger(__name__)


def get_first_non_missed_slot(cc: ConsensusClient, slot: SlotNumber, max_deep: int) -> BlockStamp:
    for i in range(slot, slot - max_deep, -1):
        try:
            root = cc.get_block_root(i).root
        except KeyError:
            logger.warning({'msg': f'Missed slot: {i}. Check next slot.'})
            continue
        except NotOkResponse as e:
            if 'Response [404]' in e.args[0]:
                logger.warning({'msg': f'Missed slot: {i}. Check next slot.'})
                continue

        slot_details = cc.get_block_details(root)

        execution_data = slot_details.message.body['execution_payload']

        return BlockStamp(
            block_root=root,
            slot_number=slot,
            state_root=slot_details.message.state_root,
            block_number=execution_data['block_number'],
            block_hash=execution_data['block_hash']
        )