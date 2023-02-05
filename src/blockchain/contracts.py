import json

from web3 import Web3

from src.variables import LIDO_CONTRACT_ADDRESS


class Contracts:
    lido = None
    oracle = None
    lido_execution_layer_rewards_vault = None
    validator_exit_bus = None
    withdrawal_queue = None

    @staticmethod
    def load_abi(abi_name: str, abi_path: str = './assets/'):
        f = open(f'{abi_path}{abi_name}.json')
        return json.load(f)

    def initialize(self, w3: Web3, abi_path='./assets/'):
        self.lido = w3.eth.contract(
            address=LIDO_CONTRACT_ADDRESS,
            abi=self.load_abi('Lido'),
        )

        self.oracle = w3.eth.contract(
            address=self.lido.functions.getOracle().call(),
            abi=self.load_abi('LidoOracle'),
        )

        self.lido_execution_layer_rewards_vault = w3.eth.contract(
            address=self.lido.functions.getELRewardsVault().call(),
            abi=self.load_abi('LidoExecutionLayerRewardsVault'),
        )

        # # ToDo get it from lido contract
        # self.validator_exit_bus = w3.eth.contract(
        #     address='0x8CEE98e5748591d8562d4897c8Bbd244eD51B2eC',
        #     abi=self.load_abi('ValidatorExitBus'),
        # )
        #
        # # ToDo get it from lido contract
        # self.withdrawal_queue = w3.eth.contract(
        #     address='0x8D2C7a3C98064E1B79374d8146A662d8C643A972',
        #     abi=self.load_abi(abi_path, 'WithdrawalQueue'),
        # )


contracts = Contracts()
