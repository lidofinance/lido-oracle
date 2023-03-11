from modules.submodules.typings import ChainConfig, FrameConfig
from tests.factory.web3_factory import Web3Factory


class ChainConfigFactory(Web3Factory):
    __model__ = ChainConfig

    slots_per_epoch = 32
    seconds_per_slot = 12
    genesis_time = 0


class FrameConfigFactory(Web3Factory):
    __model__ = FrameConfig

    initial_epoch = 0
    epochs_per_frame = 10
