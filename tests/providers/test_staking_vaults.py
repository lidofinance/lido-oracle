import pytest


@pytest.mark.testnet
@pytest.mark.integration
class TestStakingVaultsContractsSmoke:

    def test_get_burned_events(self, web3_integration):
        events = web3_integration.lido_contracts.vault_hub.get_burned_events(634086 - 1_000, 634086)
        assert len(events) != 0

    def test_get_minted_events(self, web3_integration):
        events = web3_integration.lido_contracts.vault_hub.get_minted_events(634086 - 1_000, 634086)
        assert len(events) != 0

    def test_get_updated_events(self, web3_integration):
        events = web3_integration.lido_contracts.vault_hub.get_vault_fee_updated_events(634086 - 1_000, 634_086)
        assert len(events) == 0

    def test_staking_fee_aggregate_distribution(self, web3_integration):
        out = web3_integration.lido_contracts.staking_router.get_staking_fee_aggregate_distribution()
        assert out.lido_fee_bp() != 0

    def test_vault_lazy_oracle_get_report(self, web3_integration):
        report = web3_integration.lido_contracts.lazy_oracle.get_latest_report()
        assert report is not None

    def test_get_vaults(self, web3_integration):
        vaults = web3_integration.lido_contracts.lazy_oracle.get_all_vaults()
        assert len(vaults) != 0

    def test_get_slashing_reserve(self, web3_integration):
        slashing_reserve = web3_integration.lido_contracts.oracle_daemon_config.slashing_reserve_we_right_shift()
        assert slashing_reserve != 0