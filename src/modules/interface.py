import abc

from hexbytes import HexBytes

from src.providers.typings import SlotNumber


class OracleModule(abc.ABC):
    def run_module(self, slot: SlotNumber, block_hash: HexBytes):
        pass
