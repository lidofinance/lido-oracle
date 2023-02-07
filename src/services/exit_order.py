from src.typings import Web3

from src.providers.consensus.client import ConsensusClient
from src.typings import BlockStamp


class ValidatorsExit:
    """
    Exit order is:
    1. if NO active_keys < NO current keys
    2. Stacking > 1% remove by sum validators age
    3. By active validators numbers
    """
    def __init__(self, blockstamp: BlockStamp, w3: Web3, cc: ConsensusClient,  max_size: int):
        self.blockstamp = blockstamp
        self._w3 = w3
        self._cc = cc

        # Iterator should contain only next validators
        self.max_size = max_size

    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration
