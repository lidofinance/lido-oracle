from web3 import Web3
from web3.module import Module

from src.providers.keys.client import KeysAPIClient


class KeysAPIClientModule(KeysAPIClient, Module):
    def __init__(self, hosts: list[str], w3: Web3):
        self.w3 = w3

        super(KeysAPIClient, self).__init__(hosts)
        super(Module, self).__init__()
