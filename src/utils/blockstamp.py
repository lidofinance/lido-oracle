from web3.types import Timestamp

from src.providers.consensus.client import ConsensusClient
from src.typings import BlockRoot, SlotNumber, EpochNumber, ReferenceBlockStamp, BlockStamp, BlockNumber


def build_reference_blockstamp(
    cc: ConsensusClient,
    block_root: BlockRoot,
    ref_slot: SlotNumber,
    ref_epoch: EpochNumber,
) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(
        **_build_blockstamp_data(cc, block_root),
        ref_slot=ref_slot,
        ref_epoch=ref_epoch
    )


def build_blockstamp(
    cc: ConsensusClient,
    block_root: BlockRoot,
):
    return BlockStamp(**_build_blockstamp_data(cc, block_root))


def _build_blockstamp_data(
    cc: ConsensusClient,
    block_root: BlockRoot,
) -> dict:
    slot_details = cc.get_block_details(block_root)
    execution_data = slot_details.message.body['execution_payload']

    return {
        'block_root': block_root,
        'slot_number': SlotNumber(int(slot_details.message.slot)),
        'state_root': slot_details.message.state_root,
        'block_number': BlockNumber(int(execution_data['block_number'])),
        'block_hash': execution_data['block_hash'],
        'block_timestamp': Timestamp(int(execution_data['timestamp']))
    }
