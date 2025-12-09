import logging
from functools import cached_property
from typing import cast

from web3 import Web3
from web3.contract import Contract
from web3.module import Module
from web3.types import Wei

from src import variables
from src.metrics.prometheus.business import FRAME_PREV_REPORT_REF_SLOT
from src.providers.execution.contracts.accounting import AccountingContract
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.burner import BurnerContract
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.providers.execution.contracts.lazy_oracle import LazyOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.oracle_daemon_config import (
    OracleDaemonConfigContract,
)
from src.providers.execution.contracts.oracle_report_sanity_checker import (
    OracleReportSanityCheckerContract,
)
from src.providers.execution.contracts.staking_router import StakingRouterContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.execution.contracts.withdrawal_queue_nft import (
    WithdrawalQueueNftContract,
)
from src.types import BlockStamp, ELVaultBalance, SlotNumber, WithdrawalVaultBalance
from src.utils.cache import global_lru_cache as lru_cache

logger = logging.getLogger(__name__)


class LidoContracts(Module):
    w3: Web3

    lido_locator: LidoLocatorContract
    lido: LidoContract
    accounting_oracle: AccountingOracleContract
    staking_router: StakingRouterContract
    validators_exit_bus_oracle: ExitBusOracleContract
    withdrawal_queue_nft: WithdrawalQueueNftContract
    oracle_report_sanity_checker: OracleReportSanityCheckerContract
    oracle_daemon_config: OracleDaemonConfigContract
    burner: BurnerContract

    def __init__(self, w3: Web3):
        super().__init__(w3)
        self._load_contracts()

    def __setattr__(self, key, value):
        current_value = getattr(self, key, None)
        if isinstance(current_value, Contract) and isinstance(value, Contract):
            if value.address != current_value.address:
                logger.info({'msg': f'Contract {key} has been changed to {value.address}'})
        super().__setattr__(key, value)

    def has_contract_address_changed(self) -> bool:
        addresses = [contract.address for contract in self.__dict__.values() if isinstance(contract, Contract)]
        self._load_contracts()
        new_addresses = [contract.address for contract in self.__dict__.values() if isinstance(contract, Contract)]
        return addresses != new_addresses

    def _load_contracts(self):
        # Contract that stores all lido contract addresses
        self.lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            self.w3.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS, # type: ignore
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        self.lido: LidoContract = cast(
            LidoContract,
            self.w3.eth.contract(
                address=self.lido_locator.lido(),
                ContractFactoryClass=LidoContract,
                decode_tuples=True,
            ),
        )

        self.accounting_oracle: AccountingOracleContract = cast(
            AccountingOracleContract,
            self.w3.eth.contract(
                address=self.lido_locator.accounting_oracle(),
                ContractFactoryClass=AccountingOracleContract,
                decode_tuples=True,
            ),
        )

        self.validators_exit_bus_oracle: ExitBusOracleContract = cast(
            ExitBusOracleContract,
            self.w3.eth.contract(
                address=self.lido_locator.validator_exit_bus_oracle(),
                ContractFactoryClass=ExitBusOracleContract,
                decode_tuples=True,
            ),
        )

        self.withdrawal_queue_nft: WithdrawalQueueNftContract = cast(
            WithdrawalQueueNftContract,
            self.w3.eth.contract(
                address=self.lido_locator.withdrawal_queue(),
                ContractFactoryClass=WithdrawalQueueNftContract,
                decode_tuples=True,
            ),
        )

        self.oracle_report_sanity_checker: OracleReportSanityCheckerContract = cast(
            OracleReportSanityCheckerContract,
            self.w3.eth.contract(
                address=self.lido_locator.oracle_report_sanity_checker(),
                ContractFactoryClass=OracleReportSanityCheckerContract,
                decode_tuples=True,
            ),
        )

        self.oracle_daemon_config: OracleDaemonConfigContract = cast(
            OracleDaemonConfigContract,
            self.w3.eth.contract(
                address=self.lido_locator.oracle_daemon_config(),
                ContractFactoryClass=OracleDaemonConfigContract,
                decode_tuples=True,
            ),
        )

        self.burner: BurnerContract = cast(
            BurnerContract,
            self.w3.eth.contract(
                address=self.lido_locator.burner(),
                ContractFactoryClass=BurnerContract,
                decode_tuples=True,
            ),
        )

        self.staking_router = cast(
            StakingRouterContract,
            self.w3.eth.contract(
                address=self.lido_locator.staking_router(),
                ContractFactoryClass=StakingRouterContract,
                decode_tuples=True,
            ),
        )

    @cached_property
    def accounting(self) -> AccountingContract:
        return cast(
            AccountingContract,
            self.w3.eth.contract(
                address=self.lido_locator.accounting(),
                ContractFactoryClass=AccountingContract,
                decode_tuples=True,
            ),
        )

    @cached_property
    def lazy_oracle(self) -> LazyOracleContract:
        return cast(
            LazyOracleContract,
            self.w3.eth.contract(
                address=self.lido_locator.lazy_oracle(),
                ContractFactoryClass=LazyOracleContract,
                decode_tuples=True,
            ),
        )

    @cached_property
    def vault_hub(self) -> VaultHubContract:
        return cast(
            VaultHubContract,
            self.w3.eth.contract(
                address=self.lido_locator.vault_hub(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

    # --- Contract methods ---
    @lru_cache(maxsize=1)
    def get_withdrawal_balance(self, blockstamp: BlockStamp) -> WithdrawalVaultBalance:
        return self.get_withdrawal_balance_no_cache(blockstamp)

    def get_withdrawal_balance_no_cache(self, blockstamp: BlockStamp) -> WithdrawalVaultBalance:
        return WithdrawalVaultBalance(Wei(self.w3.eth.get_balance(
            self.lido_locator.withdrawal_vault(blockstamp.block_hash),
            block_identifier=blockstamp.block_hash,
        )))

    @lru_cache(maxsize=1)
    def get_el_vault_balance(self, blockstamp: BlockStamp) -> ELVaultBalance:
        return ELVaultBalance(Wei(self.w3.eth.get_balance(
            self.lido_locator.el_rewards_vault(blockstamp.block_hash),
            block_identifier=blockstamp.block_hash,
        )))

    @lru_cache(maxsize=1)
    def get_accounting_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        FRAME_PREV_REPORT_REF_SLOT.labels('accounting').set(result)
        return result

    @lru_cache(maxsize=1)
    def get_ejector_last_processing_ref_slot(self, blockstamp: BlockStamp) -> SlotNumber:
        result = self.validators_exit_bus_oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        FRAME_PREV_REPORT_REF_SLOT.labels('ejector').set(result)
        return result
