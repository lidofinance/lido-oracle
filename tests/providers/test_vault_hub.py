# test_my_class.py

import os
from typing import cast

import pytest
from web3 import Web3

from src import variables
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.vault_hub import VaultHubContract


EXECUTION_CLIENT_URI = os.getenv('EXECUTION_CLIENT_URI')

@pytest.mark.skip(reason="Skipping all tests in this class on CI. Cause it's used for local testing")
class TestVaultHubSmoke:
    w3: Web3
    vault_hub: VaultHubContract

    def setup_method(self):
        w3 = Web3(Web3.HTTPProvider(EXECUTION_CLIENT_URI))

        lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            w3.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS,
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        self.vault_hub: VaultHubContract = cast(
            VaultHubContract,
            w3.eth.contract(
                address=lido_locator.vault_hub(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

    def test_vault_hub_pagination(self):
        vaults = self.vault_hub.get_all_vaults(limit=2)

        assert len(vaults) == 4
