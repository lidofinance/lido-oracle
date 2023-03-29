import pytest


class Web3Plugin:
    def __init__(self, web3):
        self.web3 = web3


class ChecksModule:
    def __init__(self, web3):
        self.web3 = web3

    def execute_module(self):
        return pytest.main([
            'src/modules/checks/suites',
            '-c', 'src/modules/checks/pytest.ini',
        ], plugins=[Web3Plugin(self.web3)])
