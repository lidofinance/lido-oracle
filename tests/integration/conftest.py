from typing import cast

import pytest
from web3 import HTTPProvider, Web3

from src import variables
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.burner import BurnerContract
from src.providers.execution.contracts.exit_bus_oracle import ExitBusOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.oracle_daemon_config import OracleDaemonConfigContract
from src.providers.execution.contracts.oracle_report_sanity_checker import OracleReportSanityCheckerContract
from src.providers.execution.contracts.staking_router import StakingRouterContract
from src.providers.execution.contracts.withdrawal_queue_nft import WithdrawalQueueNftContract


@pytest.fixture
def web3_provider_integration(request):
    # Some tests can be executed only on mainnet, because of not trivial selected params
    variables.LIDO_LOCATOR_ADDRESS = '0xC1d0b3DE6792Bf6b4b37EccdcC24e45978Cfd2Eb'

    w3 = Web3(HTTPProvider(variables.EXECUTION_CLIENT_URI[0], request_kwargs={'timeout': 3600}))

    assert w3.eth.chain_id == 1

    return w3


def get_contract(w3, contract_class, address):
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
