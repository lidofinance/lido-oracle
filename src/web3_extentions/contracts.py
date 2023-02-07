import json

from src.typings import Web3
from web3.module import Module

from src import variables


class LidoContracts(Module):
    def __init__(self, w3: Web3):
        super().__init__(w3)
        self._load_contracts()

    def _load_contracts(self):
        self.lido_locator = self.w3.eth.contract(
            address=variables.LIDO_LOCATOR_ADDRESS,
            abi=self.load_abi('LidoLocator'),
        )

        self.lido = self.w3.eth.contract(
            address=self.lido_locator.functions.lido().call(),
            abi=self.load_abi('Lido'),
        )

        self.oracle = self.w3.eth.contract(
            address=self.lido_locator.functions.accountingOracle().call(),
            abi=self.load_abi('LidoOracle'),
        )

        self.lido_execution_layer_rewards_vault = self.w3.eth.contract(
            address=self.lido_locator.functions.elRewardsVault().call(),
            abi=self.load_abi('LidoExecutionLayerRewardsVault'),
        )

        self.staking_router = self.w3.eth.contract(
            address=self.lido_locator.functions.stakingRouter().call(),
            abi=self.load_abi('NodeOperatorsRegistry'),
        )

        self.validator_exit_bus = self.w3.eth.contract(
            address=self.lido_locator.functions.validatorExitBus().call(),
            abi=self.load_abi('ValidatorExitBus'),
        )

        self.withdrawal_queue = self.w3.eth.contract(
            address=self.lido_locator.functions.withdrawalQueue().call(),
            abi=self.load_abi('WithdrawalQueue'),
        )

    @staticmethod
    def load_abi(abi_name: str, abi_path: str = './assets/'):
        f = open(f'{abi_path}{abi_name}.json')
        return json.load(f)
