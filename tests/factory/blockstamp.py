from eth_typing import BlockNumber, HexStr
from web3.types import Timestamp

from tests.factory.web3_factory import Web3Factory
from src.typings import BlockStamp, StateRoot, SlotNumber, BlockHash, ReferenceBlockStamp, EpochNumber


class BlockStampFactory(Web3Factory):
    __model__ = BlockStamp

    state_root: StateRoot = StateRoot(HexStr('0x623801c28526c1923f14e1bb5258e40a194059c42e280ee61c7189bf2fdbe05e'))
    slot_number: SlotNumber = SlotNumber(113500)
    block_hash: BlockHash = BlockHash(HexStr('0x4372578a683ba1c85c259a42492efbe0de9a28b1ac050b5e61065499ab80b0ca'))
    block_number: BlockNumber = BlockNumber(108006)
    block_timestamp: Timestamp = Timestamp(0)


class ReferenceBlockStampFactory(Web3Factory):
    __model__ = ReferenceBlockStamp

    state_root: StateRoot = StateRoot(HexStr('0x623801c28526c1923f14e1bb5258e40a194059c42e280ee61c7189bf2fdbe05e'))
    slot_number: SlotNumber = SlotNumber(113500)
    block_hash: BlockHash = BlockHash(HexStr('0x4372578a683ba1c85c259a42492efbe0de9a28b1ac050b5e61065499ab80b0ca'))
    block_number: BlockNumber = BlockNumber(108006)
    block_timestamp: Timestamp = Timestamp(0)

    ref_slot: SlotNumber = SlotNumber(113500)
    ref_epoch: EpochNumber = EpochNumber(113500//32)
