from web3 import Web3
from web3.module import Module

from providers.consensus.client import ConsensusClient
from variables import (
    HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
    HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    HTTP_REQUEST_TIMEOUT_CONSENSUS,
)


class ConsensusClientModule(ConsensusClient, Module):
    def __init__(self, hosts: list[str], w3: Web3):
        self.w3 = w3
        super().__init__(
            hosts,
            HTTP_REQUEST_TIMEOUT_CONSENSUS,
            HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
            HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
            chain_id=w3.eth.chain_id,
        )
        super(Module, self).__init__()
