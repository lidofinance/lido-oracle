import json

from web3 import Web3
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

        self.accounting_oracle = self.w3.eth.contract(
            address=self.lido_locator.functions.accountingOracle().call(),
            abi=self.load_abi('AccountingOracle'),
        )

        self.lido_execution_layer_rewards_vault = self.w3.eth.contract(
            address=self.lido_locator.functions.elRewardsVault().call(),
            abi=self.load_abi('LidoExecutionLayerRewardsVault'),
        )

        self.withdrawal_vault = self.w3.eth.contract(
            address=self.lido_locator.functions.withdrawalVault().call(),
            abi=self.load_abi('WithdrawalVault'),
        )

        self.staking_router = self.w3.eth.contract(
            address=self.lido_locator.functions.stakingRouter().call(),
            abi=self.load_abi('StakingRouter'),
        )

        self.validators_exit_bus_oracle = self.w3.eth.contract(
            address=self.lido_locator.functions.validatorsExitBusOracle().call(),
            abi=self.load_abi('ValidatorsExitBusOracle'),
        )

        self.withdrawal_queue = self.w3.eth.contract(
            address=self.lido_locator.functions.withdrawalQueue().call(),
            abi=self.load_abi('WithdrawalRequestNFT'),
        )
        self.oracleReportSanityChecker = self.w3.eth.contract(
            address=self.lido_locator.functions.oracleReportSanityChecker().call(),
            abi=self.load_abi('OracleReportSanityChecker'),
        )

    @staticmethod
    def load_abi(abi_name: str, abi_path: str = './assets/'):
        f = open(f'{abi_path}{abi_name}.json')
        return json.load(f)
