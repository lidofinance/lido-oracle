from typing import cast

import pytest

from src import variables
from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.vault_hub import VaultHubContract


@pytest.mark.testnet
@pytest.mark.integration
class TestVaultHubSmoke:

    @pytest.fixture
    def vault_hub(self, web3_integration):
        lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            web3_integration.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS,
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        return cast(
            VaultHubContract,
            web3_integration.eth.contract(
                address=lido_locator.vault_hub(),
                ContractFactoryClass=VaultHubContract,
                decode_tuples=True,
            ),
        )

    def test_vault_hub_pagination(self, vault_hub):
        vaults = vault_hub.get_all_vaults(limit=15)

        assert len(vaults) == vault_hub.get_vaults_count()
