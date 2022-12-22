import json

from web3 import Web3

from src.variables import LIDO_CONTRACT_ADDRESS, MERKLE_PRICE_ORACLE_CONTRACT


class Contracts:
    lido = None
    oracle = None
    lido_execution_layer_rewards_vault = None
    validator_exit_bus = None
    withdrawal_queue = None
    pool = None

    @staticmethod
    def _load_abi(abi_path, abi_name):
        f = open(f'{abi_path}{abi_name}.json')
        return json.load(f)

    def initialize(self, w3: Web3, abi_path='./assets/'):
        self.lido = w3.eth.contract(
            address=LIDO_CONTRACT_ADDRESS,
            abi=self._load_abi(abi_path, 'Lido'),
        )

        self.oracle = w3.eth.contract(
            # address=self.lido.functions.getOracle().call(),
            address='0xa71CC47158c15d5D8b3Af4c6390e8608d08c2994',
            abi=self._load_abi(abi_path, 'LidoOracle'),
        )

        self.lido_execution_layer_rewards_vault = w3.eth.contract(
            address=self.lido.functions.getELRewardsVault().call(),
            abi=self._load_abi(abi_path, 'LidoExecutionLayerRewardsVault'),
        )

        self.validator_exit_bus = w3.eth.contract(
            address='0x8CEE98e5748591d8562d4897c8Bbd244eD51B2eC',
            abi=self._load_abi(abi_path, 'ValidatorExitBus'),
        )

        self.withdrawal_queue = w3.eth.contract(
            address='0x8D2C7a3C98064E1B79374d8146A662d8C643A972',
            abi=self._load_abi(abi_path, 'WithdrawalQueue'),
        )

        # self.pool = w3.eth.contract(
        #     address=self.oracle.functions.pool().call(),
        #     address=self.oracle.functions.pool().call(),
        #     abi=self._load_abi(abi_path, 'Pool'),
        # )

        # self.merkle_price_oracle = w3.eth.contract(
        #     address=MERKLE_PRICE_ORACLE_CONTRACT,
        #     abi=self._load_abi(abi_path, 'StableSwapStateOracle'),
        # )


contracts = Contracts()
