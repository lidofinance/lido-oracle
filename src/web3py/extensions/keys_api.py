from web3 import Web3
from web3.module import Module

from src.providers.keys.client import KeysAPIClient
from src.variables import (
    HTTP_REQUEST_TIMEOUT_KEYS_API,
    HTTP_REQUEST_RETRY_COUNT_KEYS_API,
    HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API
)


class KeysAPIClientModule(KeysAPIClient, Module):
    def __init__(self, hosts: list[str], w3: Web3):
        self.w3 = w3

        super(KeysAPIClient, self).__init__(
            hosts,
            HTTP_REQUEST_TIMEOUT_KEYS_API,
            HTTP_REQUEST_RETRY_COUNT_KEYS_API,
            HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_KEYS_API
        )
        super(Module, self).__init__()
