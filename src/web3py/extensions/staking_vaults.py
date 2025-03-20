import logging
from typing import TYPE_CHECKING, cast

from web3 import Web3
from web3.module import Module

from src.modules.accounting.types import VaultsReport
from src.providers.consensus.types import Validator, PendingDeposit
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.staking_vault import StakingVaultContract
from src.providers.execution.contracts.vault_hub import VaultHubContract

from src import variables
from src.types import BlockStamp
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.web3py.types import Web3  # pragma: no cover

class StakingVaults(Module):
    w3: 'Web3'

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
                address=self.lido_locator.vault_hub(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

    def _load_vault(self, vault_id: int, blockstamp: BlockStamp) -> StakingVaultContract:
        """
        Returns the StakingVaultContract instance by the given address.
        """
        socket = self.vault_hub.vault_socket(vault_id, blockstamp)
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

    @lru_cache(maxsize=1)
    def _get_validators(self, blockstamp: BlockStamp) -> list[Validator]:
        """
        Cached method to get validators for a specific blockstamp.
        """
        return self.w3.cc.get_validators(blockstamp)

    @lru_cache(maxsize=1)
    def _get_pending_deposits(self, blockstamp: BlockStamp) -> list[PendingDeposit]:
        """
        Cached method to get pending deposits for a specific blockstamp.
        """
        return self.w3.cc.get_pending_deposits(blockstamp)

    @lru_cache(maxsize=1)
    def _get_validator_cl_balance(self, blockstamp: BlockStamp, vault_withdrawal_credentials: str) -> int:
        """
        Returns the CL balance of the validator with the given withdrawal credentials.
        """
        validators = self._get_validators(blockstamp)
        for validator in validators:
            if validator.validator.withdrawal_credentials == vault_withdrawal_credentials:
                return Web3.to_wei(int(validator.balance), 'gwei')
        
        return 0

    @lru_cache(maxsize=1)
    def _get_validator_pending_balance(self, blockstamp: BlockStamp, vault_withdrawal_credentials: str) -> int:
        """
        Returns the pending balance of the validator with the given withdrawal credentials.
        """
        pending_deposits = self._get_pending_deposits(blockstamp)
        for pending_deposit in pending_deposits:
            if pending_deposit.withdrawal_credentials == vault_withdrawal_credentials:
                return Web3.to_wei(int(pending_deposit.amount), 'gwei')
        
        return 0

    @lru_cache(maxsize=1)
    def _get_vault_value(self, vault: StakingVaultContract, blockstamp: BlockStamp) -> int:
        """
        Calculate the total value of a vault including EL balance, CL balance, and pending deposits.
        """
        vault_withdrawal_credentials = vault.withdrawal_credentials(blockstamp)
        
        # Get vault values for the report
        vault_balance = self.w3.eth.get_balance(vault.address, block_identifier=blockstamp.block_hash)
        vault_cl_balance = self._get_validator_cl_balance(blockstamp, vault_withdrawal_credentials)
        vault_pending_deposits = self._get_validator_pending_balance(blockstamp, vault_withdrawal_credentials)
        
        return vault_balance + vault_cl_balance + vault_pending_deposits

    def get_vaults_state(self, blockstamp: BlockStamp) -> VaultsReport:
        vaults_values = []
        vaults_in_out_deltas = []

        vaults_count = self.get_vaults_count(blockstamp)

        for vault_id in range(vaults_count):
            vault = self._load_vault(vault_id, blockstamp)
            
            # Get vault in/out delta for the report
            vault_in_out_delta = vault.in_out_delta(blockstamp)
            vaults_in_out_deltas.append(vault_in_out_delta)

            # Get vault value
            vault_value = self._get_vault_value(vault, blockstamp)
            vaults_values.append(vault_value)

            logger.info({
                'msg': f'Vault values for vault: {vault.address}.',
                'vault_in_out_delta': vault_in_out_delta,
                'vault_value': vault_value,
            })

        return vaults_values, vaults_in_out_deltas