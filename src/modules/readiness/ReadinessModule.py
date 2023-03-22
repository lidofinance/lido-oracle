import pytest


class Web3Plugin:
    def __init__(self, web3):
        self.web3 = web3


class ReadinessModule:
    def __init__(self, web3):
        self.web3 = web3

    def execute_module(self):
        return pytest.main([
            'src/modules/readiness/checks',
            '-c', 'src/modules/readiness/pytest.ini',
        ], plugins=[Web3Plugin(self.web3)])
