from src.typings import SlotNumber, EpochNumber, FrameNumber
from src.modules.submodules.typings import ChainConfig, FrameConfig


class Web3Converter:
    """
    The Web3Converter class contains methods for converting between slot, epoch, and frame numbers using chain and
    frame settings passed as arguments when the class instance is created.

    Frame is the distance between two oracle reports.
    """

    chain_config: ChainConfig
    frame_config: FrameConfig

    def __init__(self, chain_config: ChainConfig, frame_config: FrameConfig):
        self.chain_config = chain_config
        self.frame_config = frame_config

    def get_epoch_first_slot(self, epoch: EpochNumber) -> SlotNumber:
        return SlotNumber(epoch * self.chain_config.slots_per_epoch)

    def get_frame_last_slot(self, frame: FrameNumber) -> SlotNumber:
        return SlotNumber(self.get_frame_first_slot(FrameNumber(frame + 1)) - 1)

    def get_frame_first_slot(self, frame: FrameNumber) -> SlotNumber:
        return SlotNumber(
            (self.frame_config.initial_epoch + frame * self.frame_config.epochs_per_frame) * self.chain_config.slots_per_epoch
        )

    def get_epoch_by_slot(self, ref_slot: SlotNumber) -> EpochNumber:
        return EpochNumber(ref_slot // self.chain_config.slots_per_epoch)

    def get_epoch_by_timestamp(self, timestamp: int) -> EpochNumber:
        return EpochNumber(self.get_slot_by_timestamp(timestamp) // self.chain_config.slots_per_epoch)

    def get_slot_by_timestamp(self, timestamp: int) -> SlotNumber:
        return SlotNumber((timestamp - self.chain_config.genesis_time) // self.chain_config.seconds_per_slot)

    def get_frame_by_slot(self, slot: SlotNumber) -> FrameNumber:
        return self.get_frame_by_epoch(self.get_epoch_by_slot(slot))

    def get_frame_by_epoch(self, epoch: EpochNumber) -> FrameNumber:
        return FrameNumber((epoch - self.frame_config.initial_epoch) // self.frame_config.epochs_per_frame)
