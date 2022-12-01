import abc

from hexbytes import HexBytes

from src.providers.typings import Slot


class OracleModule(abc.ABC):
    def run_module(self, slot: Slot, block_hash: HexBytes):
        pass
