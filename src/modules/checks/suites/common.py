import pytest

from src.modules.accounting.accounting import Accounting
from src.modules.ejector.ejector import Ejector


@pytest.fixture()
def web3(web3):
    if not hasattr(web3, 'lido_contracts'):
        pytest.skip('LIDO_LOCATOR_ADDRESS is not set')
    return web3


@pytest.fixture()
def accounting(web3):
    return Accounting(web3)


@pytest.fixture()
def ejector(web3):
    return Ejector(web3)


def check_accounting_contract_configs(accounting):
    """Make sure accounting contract configs are valid"""
    accounting.check_contract_configs()


def check_ejector_contract_configs(ejector):
    """Make sure ejector contract configs are valid"""
    ejector.check_contract_configs()
