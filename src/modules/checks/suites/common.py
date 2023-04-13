"""Common checks"""
import pytest

from src.main import check_providers_chain_ids as chain_ids_check  # rename to not conflict with test
from src.modules.accounting.accounting import Accounting
from src.modules.ejector.ejector import Ejector


@pytest.fixture()
def skip_locator(web3):
    if not hasattr(web3, 'lido_contracts'):
        pytest.skip('LIDO_LOCATOR_ADDRESS is not set')


@pytest.fixture()
def accounting(web3, skip_locator):
    return Accounting(web3)


@pytest.fixture()
def ejector(web3, skip_locator):
    return Ejector(web3)


def check_providers_chain_ids(web3):
    """Make sure all providers are on the same chain"""
    chain_ids_check(web3, web3.cc, web3.kac)


def check_accounting_contract_configs(accounting):
    """Make sure accounting contract configs are valid"""
    accounting.check_contract_configs()


def check_ejector_contract_configs(ejector):
    """Make sure ejector contract configs are valid"""
    ejector.check_contract_configs()
