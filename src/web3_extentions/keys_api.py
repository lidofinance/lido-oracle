from src.typings import Web3
from web3.module import Module

from src.providers.keys.client import KeysAPIClient


class KeysAPIClientModule(KeysAPIClient, Module):
    def __init__(self, host: str, w3: Web3):
        self.w3 = w3

        super(KeysAPIClient, self).__init__(host)
        super(Module, self).__init__()
