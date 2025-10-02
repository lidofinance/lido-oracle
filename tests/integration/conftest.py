from typing import cast

import pytest
from web3 import HTTPProvider, Web3

from src import variables
from src.providers.execution.contracts.accounting import AccountingContract
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.burner import BurnerContract
from src.providers.execution.contracts.cs_accounting import CSAccountingContract
from src.providers.execution.contracts.cs_fee_distributor import (
    CSFeeDistributorContract,
)
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.contracts.cs_module import CSModuleContract
from src.providers.execution.contracts.cs_parameters_registry import (
    CSParametersRegistryContract,
)
from src.providers.execution.contracts.cs_strikes import CSStrikesContract
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


@pytest.fixture
def web3_provider_integration(request):
    w3 = Web3(HTTPProvider(variables.EXECUTION_CLIENT_URI[0], request_kwargs={'timeout': 3600}))

    return w3


def get_contract(w3, contract_class, address):
    assert address, "No address given"
    return cast(
        contract_class,
        w3.eth.contract(
            address=address,
            ContractFactoryClass=contract_class,
            decode_tuples=True,
        ),
    )


@pytest.fixture
def lido_locator_contract(web3_provider_integration) -> LidoLocatorContract:
    return get_contract(
        web3_provider_integration,
        LidoLocatorContract,
        variables.LIDO_LOCATOR_ADDRESS,
    )


@pytest.fixture
def lido_contract(web3_provider_integration, lido_locator_contract) -> LidoContract:
    return get_contract(
        web3_provider_integration,
        LidoContract,
        lido_locator_contract.lido(),
    )


@pytest.fixture
def accounting_oracle_contract(web3_provider_integration, lido_locator_contract) -> AccountingOracleContract:
    return get_contract(
        web3_provider_integration,
        AccountingOracleContract,
        lido_locator_contract.accounting_oracle(),
    )


@pytest.fixture
def accounting_contract(web3_provider_integration, lido_locator_contract) -> AccountingContract:
    return get_contract(
        web3_provider_integration,
        AccountingContract,
        lido_locator_contract.accounting(),
    )


@pytest.fixture
def staking_router_contract(web3_provider_integration, lido_locator_contract) -> StakingRouterContract:
    return get_contract(
        web3_provider_integration,
        StakingRouterContract,
        lido_locator_contract.staking_router(),
    )


@pytest.fixture
def validators_exit_bus_oracle_contract(web3_provider_integration, lido_locator_contract) -> ExitBusOracleContract:
    return get_contract(
        web3_provider_integration,
        ExitBusOracleContract,
        lido_locator_contract.validator_exit_bus_oracle(),
    )


@pytest.fixture
def withdrawal_queue_nft_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration,
        WithdrawalQueueNftContract,
        lido_locator_contract.withdrawal_queue(),
    )


@pytest.fixture
def oracle_report_sanity_checker_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration,
        OracleReportSanityCheckerContract,
        lido_locator_contract.oracle_report_sanity_checker(),
    )


@pytest.fixture
def oracle_daemon_config_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration,
        OracleDaemonConfigContract,
        lido_locator_contract.oracle_daemon_config(),
    )


@pytest.fixture
def burner_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration,
        BurnerContract,
        lido_locator_contract.burner(),
    )


@pytest.fixture
def vault_hub_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration,
        VaultHubContract,
        lido_locator_contract.vault_hub(),
    )


@pytest.fixture
def lazy_oracle_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration,
        LazyOracleContract,
        lido_locator_contract.lazy_oracle(),
    )


# ╔══════════════════════════════════════════════════════════════════════════════════════════════════╗
# ║                                          CSM contracts                                           ║
# ╚══════════════════════════════════════════════════════════════════════════════════════════════════╝


@pytest.fixture
def cs_module_contract(web3_provider_integration):
    return get_contract(
        web3_provider_integration,
        CSModuleContract,
        "0xdA7dE2ECdDfccC6c3AF10108Db212ACBBf9EA83F",  # mainnet deploy
    )


@pytest.fixture
def cs_accounting_contract(web3_provider_integration, cs_module_contract):
    return get_contract(
        web3_provider_integration,
        CSAccountingContract,
        cs_module_contract.accounting(),
    )


@pytest.fixture
def cs_params_contract(web3_provider_integration, cs_module_contract):
    return get_contract(
        web3_provider_integration,
        CSParametersRegistryContract,
        cs_module_contract.parameters_registry(),
    )


@pytest.fixture
def cs_fee_distributor_contract(web3_provider_integration, cs_accounting_contract):
    return get_contract(
        web3_provider_integration,
        CSFeeDistributorContract,
        cs_accounting_contract.fee_distributor(),
    )


@pytest.fixture
def cs_fee_oracle_contract(web3_provider_integration, cs_fee_distributor_contract):
    return get_contract(
        web3_provider_integration,
        CSFeeOracleContract,
        cs_fee_distributor_contract.oracle(),
    )


@pytest.fixture
def cs_strikes_contract(web3_provider_integration, cs_fee_oracle_contract):
    return get_contract(
        web3_provider_integration,
        CSStrikesContract,
        cs_fee_oracle_contract.strikes(),
    )
