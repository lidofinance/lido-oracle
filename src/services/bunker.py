from web3 import Web3

from src.providers.consensus.client import ConsensusClient
from src.providers.keys.client import KeysAPIClient


class BunkerService:
    def __init__(self, web3: Web3, cc: ConsensusClient, kac: KeysAPIClient):
        self._w3 = web3
        self._cc = cc
        self._kac = kac

    def is_bunker_mode(self) -> bool:
        pass

    def _check_slashings(self):
        pass

    def _check_activity_leak(self):
        pass
