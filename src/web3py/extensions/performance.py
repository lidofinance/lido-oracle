from web3 import Web3
from web3.module import Module

from src.providers.performance.client import PerformanceClient
from src.variables import (
    HTTP_REQUEST_TIMEOUT_PERFORMANCE,
    HTTP_REQUEST_RETRY_COUNT_PERFORMANCE,
    HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_PERFORMANCE,
)


class PerformanceClientModule(PerformanceClient, Module):
    def __init__(self, hosts: list[str]):

        super(PerformanceClient, self).__init__(
            hosts,
            HTTP_REQUEST_TIMEOUT_PERFORMANCE,
            HTTP_REQUEST_RETRY_COUNT_PERFORMANCE,
            HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_PERFORMANCE,
        )
        super(Module, self).__init__()
