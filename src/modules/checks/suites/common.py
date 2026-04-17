"""Common checks"""

import pytest

from modules.oracles.accounting.accounting import Accounting
from modules.oracles.common.runtime import (
    check_providers_chain_ids as chain_ids_check,  # rename to not conflict with test
)
from modules.oracles.ejector.ejector import Ejector
from modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from modules.oracles.staking_modules.curated.cm import CMPerformanceOracle


@pytest.fixture()
def skip_locator(web3):
    if not hasattr(web3, 'lido_contracts'):
        pytest.skip('LIDO_LOCATOR_ADDRESS is not set')


@pytest.fixture()
def skip_csm(web3_cs_module):
    contract_version = web3_cs_module.staking_module.oracle.get_contract_version()
    if contract_version != CSPerformanceOracle.COMPATIBLE_CONTRACT_VERSION:
        pytest.skip(
            f'Staking module contract version {contract_version} is not compatible with CSM '
            f'(expected {CSPerformanceOracle.COMPATIBLE_CONTRACT_VERSION})'
        )


@pytest.fixture()
def skip_cm(web3_curated_module):
    contract_version = web3_curated_module.staking_module.oracle.get_contract_version()
    if contract_version != CMPerformanceOracle.COMPATIBLE_CONTRACT_VERSION:
        pytest.skip(
            f'Staking module contract version {contract_version} is not compatible with Curated Module '
            f'(expected {CMPerformanceOracle.COMPATIBLE_CONTRACT_VERSION})'
        )


@pytest.fixture()
def accounting(web3, skip_locator):
    return Accounting(web3)


@pytest.fixture()
def ejector(web3, skip_locator):
    return Ejector(web3)


@pytest.fixture()
def csm(web3_cs_module, skip_csm):
    return CSPerformanceOracle(web3_cs_module)


@pytest.fixture()
def cm(web3_curated_module, skip_cm):
    return CMPerformanceOracle(web3_curated_module)


def check_providers_chain_ids(web3):
    """Make sure all providers are on the same chain"""
    chain_ids_check(web3, web3.cc, web3.kac)


def check_accounting_contract_configs(accounting):
    """Make sure accounting contract configs are valid"""
    accounting.check_contract_configs()


def check_ejector_contract_configs(ejector):
    """Make sure ejector contract configs are valid"""
    ejector.check_contract_configs()


def check_csm_contract_configs(csm):
    """Make sure csm contract configs are valid"""
    csm.check_contract_configs()


def check_cm_contract_configs(cm):
    """Make sure cm contract configs are valid"""
    cm.check_contract_configs()
