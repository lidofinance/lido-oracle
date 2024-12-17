import logging
from typing import cast

from eth_typing import ChecksumAddress
from web3 import Web3
from web3.module import Module

from src.modules.accounting.types import VaultSocket, VaultsReport
from src.providers.consensus.types import Validator
from src.providers.execution.contracts.staking_vault import StakingVaultContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src import variables

from src.types import BlockStamp
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class LidoVaults(Module):
    w3: Web3

    lido_locator: LidoLocatorContract
    vault_hub: VaultHubContract

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self._load_vaults_contracts()

    def _load_vaults_contracts(self):
        # Contract that stores all lido contract addresses
        self.lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            self.w3.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS,
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        self.vault_hub: VaultHubContract = cast(
            VaultHubContract,
            self.w3.eth.contract(
                address=self.lido_locator.accounting(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

    def _load_vault(self, socket: VaultSocket) -> StakingVaultContract:
        """
        Returns the StakingVaultContract instance by the given VaultSocket.
        """

        return cast(
            StakingVaultContract,
            self.w3.eth.contract(
                address=socket.vault,
                ContractFactoryClass=StakingVaultContract,
                decode_tuples=True,
            ),
        )

    @lru_cache(maxsize=1)
    def get_vaults_count(self, blockstamp: BlockStamp) -> int:
        return self.vault_hub.get_vaults_count(blockstamp)

    @staticmethod
    def get_validator_cl_balance(validators: list[Validator], vault_address: ChecksumAddress) -> int:
        validator_cl_balance = 0

        for validator in validators:
            if validator.validator.withdrawal_credentials == vault_address:
                validator_cl_balance = int(validator.balance)
                break

        return validator_cl_balance

    def get_vaults_data(self, validators: list[Validator], blockstamp: BlockStamp) -> VaultsReport:
        vaults_count = self.get_vaults_count(blockstamp)
        vaults_values = []
        vaults_net_cash_flows = []

        for vault_id in range(vaults_count):
            socket = self.vault_hub.vault_socket(vault_id, blockstamp)
            vault = self._load_vault(socket)

            # Get vault in/out delta for the report
            vault_in_out_delta = vault.in_out_delta(blockstamp)
            vaults_net_cash_flows.append(vault_in_out_delta)

            # Get vault values for the report
            vault_balance = self.w3.eth.get_balance(vault.address, block_identifier=blockstamp.block_hash)
            vault_cl_balance = self.get_validator_cl_balance(validators, socket.vault)

            vault_value = vault_balance + vault_cl_balance
            vaults_values.append(vault_value)

            logger.info({
                'msg': f'Vault values for vault #{vault_id}.',
                'vault_in_out_delta': vault_in_out_delta,
                'vault_value': vault_value,
            })

        return vaults_values, vaults_net_cash_flows
