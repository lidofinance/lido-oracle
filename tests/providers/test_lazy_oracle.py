import pytest


@pytest.mark.testnet
@pytest.mark.integration
class TestLazyOracleHubSmoke:

    def test_vault_lazy_oracle_get_report(self, web3_integration):
        report = web3_integration.lido_contracts.lazy_oracle.get_report(block_identifier='latest')
        assert report is not None

    def test_get_vaults(self, web3_integration):
        vaults = web3_integration.lido_contracts.lazy_oracle.get_all_vaults(block_identifier='latest')
        assert len(vaults) != 0
