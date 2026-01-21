from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber

from src import variables
from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import (
    VaultAddresses,
    VaultInfoFactory,
    WithdrawalCredentials,
)

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestGetVaults:

    def test_get_vaults_uses_specific_block_identifier(self, web3):
        # Setup
        vault_0 = VaultInfoFactory.build(
            vault=VaultAddresses.VAULT_0,
            withdrawal_credentials=WithdrawalCredentials.WC_0,
        )
        vault_1 = VaultInfoFactory.build(
            vault=VaultAddresses.VAULT_1,
            withdrawal_credentials=WithdrawalCredentials.WC_1,
        )

        class LazyOracleStub:
            def __init__(self, vaults):
                self.vaults = vaults
                self.get_vaults_count = MagicMock(return_value=len(vaults))
                self.get_vaults = MagicMock(return_value=vaults)

            def get_all_vaults(self, block_identifier="latest"):
                self.get_vaults_count(block_identifier=block_identifier)
                self.get_vaults(
                    block_identifier=block_identifier,
                    offset=0,
                    limit=variables.VAULT_PAGINATION_LIMIT,
                )
                return self.vaults

        lazy_oracle = LazyOracleStub([vault_0, vault_1])
        web3.lido_contracts.lazy_oracle = lazy_oracle

        service = StakingVaultsService(web3)
        block_identifier = BlockNumber(1234)

        # Act
        result = service.get_vaults(block_identifier=block_identifier)

        # Assert
        lazy_oracle.get_vaults_count.assert_called_once_with(block_identifier=block_identifier)
        lazy_oracle.get_vaults.assert_called_once_with(
            block_identifier=block_identifier,
            offset=0,
            limit=variables.VAULT_PAGINATION_LIMIT,
        )
        assert result == {VaultAddresses.VAULT_0: vault_0, VaultAddresses.VAULT_1: vault_1}
