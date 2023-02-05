from abc import ABC

from web3 import Web3

from src.providers.consensus.client import ConsensusClient


class ProviderModule(ABC):
    def __init__(self, web3: Web3, consensus_client: ConsensusClient):
        self._w3 = web3
        self._cc = consensus_client
