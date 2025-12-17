"""Common checks"""
import pytest

from src.modules.oracles.common.runtime import check_providers_chain_ids as chain_ids_check  # rename to not conflict with test
from src.modules.oracles.accounting.accounting import Accounting
from src.modules.oracles.ejector.ejector import Ejector
from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from src.modules.oracles.staking_modules.curated.cm import CMPerformanceOracle


@pytest.fixture()
def skip_locator(web3):
    if not hasattr(web3, 'lido_contracts'):
        pytest.skip('LIDO_LOCATOR_ADDRESS is not set')


@pytest.fixture()
def skip_csm(web3):
    if not hasattr(web3, 'csm'):
        pytest.skip('STAKING_MODULE_ADDRESS is not set')


@pytest.fixture()
def accounting(web3, skip_locator):
    return Accounting(web3)


@pytest.fixture()
def ejector(web3, skip_locator):
    return Ejector(web3)


@pytest.fixture()
def csm(web3, skip_locator, skip_csm):
    return CSPerformanceOracle(web3)


@pytest.fixture()
def cm(web3, skip_locator, skip_csm):
    return CMPerformanceOracle(web3)


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

