from eth_typing import BlockNumber, HexStr
from web3.types import Timestamp

from src.types import BlockStamp, StateRoot, SlotNumber, BlockHash, ReferenceBlockStamp, EpochNumber
from tests.factory.web3_factory import Web3DataclassFactory


class BlockStampFactory(Web3DataclassFactory[BlockStamp]):
    state_root: StateRoot = StateRoot(HexStr('0xc4298fa1a4df250710d3e13d16fae7e4cc3ad52809745d86e1f1772abe04702b'))
    slot_number: SlotNumber = SlotNumber(294271)
    block_hash: BlockHash = BlockHash(HexStr('0x0d339fdfa3018561311a39bf00568ed08048055082448d17091d5a4dc2fa035b'))
    block_number: BlockNumber = BlockNumber(281479)
    block_timestamp: Timestamp = Timestamp(1678794852)


class ReferenceBlockStampFactory(Web3DataclassFactory[ReferenceBlockStamp]):
    state_root: StateRoot = StateRoot(HexStr('0xc4298fa1a4df250710d3e13d16fae7e4cc3ad52809745d86e1f1772abe04702b'))
    slot_number: SlotNumber = SlotNumber(294271)
    block_hash: BlockHash = BlockHash(HexStr('0x0d339fdfa3018561311a39bf00568ed08048055082448d17091d5a4dc2fa035b'))
    block_number: BlockNumber = BlockNumber(281479)
    block_timestamp: Timestamp = Timestamp(1678794852)

    ref_slot: SlotNumber = SlotNumber(294271)
    ref_epoch: EpochNumber = EpochNumber(9195)
