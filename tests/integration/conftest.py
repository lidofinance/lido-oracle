from dataclasses import dataclass
from typing import cast

import pytest
from web3 import Web3, HTTPProvider

from src import variables
from src.providers.execution.contracts.accounting import AccountingContract
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.burner import BurnerContract
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.oracle_daemon_config import OracleDaemonConfigContract
from src.providers.execution.contracts.oracle_report_sanity_checker import OracleReportSanityCheckerContract
from src.providers.execution.contracts.staking_router import StakingRouterContractV1, StakingRouterContractV2
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.execution.contracts.withdrawal_queue_nft import WithdrawalQueueNftContract

from tests.integration.environments import ENVIRONMENTS


def get_contract(w3, contract_class, address):
    return cast(
        contract_class,
        w3.eth.contract(
            address=address,
            ContractFactoryClass=contract_class,
            decode_tuples=True,
        ),
    )


@dataclass
class Web3ProviderIntegration:
    web3: Web3
    lido_locator_address: str


@pytest.fixture
def web3_provider_integration(request) -> Web3ProviderIntegration:
    env_name = getattr(request, 'param', 'mainnet')  # Default to 'mainnet'
    env_config = ENVIRONMENTS.get(env_name, None)

    if not env_config:
        raise ValueError(f"Invalid environment: {env_name}. Available environments: {', '.join(ENVIRONMENTS.keys())}")

    w3 = Web3(HTTPProvider(env_config.execution_client_uri, request_kwargs={"timeout": 3600}))
    assert w3.eth.chain_id == env_config.chain_id

    return Web3ProviderIntegration(
        web3=w3,
        lido_locator_address=env_config.lido_locator_address,
    )


@pytest.fixture
def lido_locator_contract(web3_provider_integration) -> LidoLocatorContract:
    return get_contract(
        web3_provider_integration.web3,
        LidoLocatorContract,
        web3_provider_integration.lido_locator_address,
    )


@pytest.fixture
def lido_contract(web3_provider_integration, lido_locator_contract) -> LidoContract:
    return get_contract(
        web3_provider_integration.web3,
        LidoContract,
        lido_locator_contract.lido(),
    )


@pytest.fixture
def accounting_contract(web3_provider_integration, lido_locator_contract) -> LidoContract:
    return get_contract(
        web3_provider_integration.web3,
        AccountingContract,
        lido_locator_contract.accounting(),
    )


@pytest.fixture
def accounting_oracle_contract(web3_provider_integration, lido_locator_contract) -> AccountingOracleContract:
    return get_contract(
        web3_provider_integration.web3,
        AccountingOracleContract,
        lido_locator_contract.accounting_oracle(),
    )


@pytest.fixture
def staking_router_contract(web3_provider_integration, lido_locator_contract) -> StakingRouterContractV1:
    return get_contract(
        web3_provider_integration.web3,
        StakingRouterContractV1,
        lido_locator_contract.staking_router(),
    )


@pytest.fixture
def staking_router_contract_v2(web3_provider_integration, lido_locator_contract) -> StakingRouterContractV2:
    return get_contract(
        web3_provider_integration.web3,
        StakingRouterContractV2,
        lido_locator_contract.staking_router(),
    )


@pytest.fixture
def validators_exit_bus_oracle_contract(web3_provider_integration, lido_locator_contract) -> ExitBusOracleContract:
    return get_contract(
        web3_provider_integration.web3,
        ExitBusOracleContract,
        lido_locator_contract.validator_exit_bus_oracle(),
    )


@pytest.fixture
def withdrawal_queue_nft_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration.web3,
        WithdrawalQueueNftContract,
        lido_locator_contract.withdrawal_queue(),
    )


@pytest.fixture
def oracle_report_sanity_checker_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration.web3,
        OracleReportSanityCheckerContract,
        lido_locator_contract.oracle_report_sanity_checker(),
    )


@pytest.fixture
def oracle_daemon_config_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration.web3,
        OracleDaemonConfigContract,
        lido_locator_contract.oracle_daemon_config(),
    )


@pytest.fixture
def burner_contract(web3_provider_integration, lido_locator_contract):
    return get_contract(
        web3_provider_integration.web3,
        BurnerContract,
        lido_locator_contract.burner(),
    )


@pytest.fixture
def vault_hub_contract(web3_provider_integration, lido_locator_contract) -> VaultHubContract:
    return get_contract(
        web3_provider_integration.web3,
        VaultHubContract,
        lido_locator_contract.accounting(),  # accounting contract is inherited from vault hub contract
    )
