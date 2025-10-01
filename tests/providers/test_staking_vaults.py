import pytest
from eth_typing import BlockNumber


@pytest.mark.testnet
@pytest.mark.integration
class TestStakingVaultsContractsSmoke:

    @pytest.mark.skip("No events in the range, need to update the test")
    def test_get_burned_events(self, web3_integration):
        events = web3_integration.lido_contracts.vault_hub.get_burned_events(
            BlockNumber(1272666 - 1_000), BlockNumber(1272666)
        )
        assert len(events) != 0

    @pytest.mark.skip("No events in the range, need to update the test")
    def test_get_minted_events(self, web3_integration):
        events = web3_integration.lido_contracts.vault_hub.get_minted_events(
            BlockNumber(1272666 - 1_000), BlockNumber(1272666)
        )
        assert len(events) != 0

    def test_get_updated_events(self, web3_integration):
        events = web3_integration.lido_contracts.vault_hub.get_vault_fee_updated_events(
            BlockNumber(1272666 - 1_000), BlockNumber(1272666)
        )
        assert len(events) == 0

    @pytest.mark.skip("Distribution disabled on devnet")
    def test_staking_fee_aggregate_distribution(self, web3_integration):
        out = web3_integration.lido_contracts.staking_router.get_staking_fee_aggregate_distribution()
        assert 0 != out.lido_fee_bp()

    def test_vault_lazy_oracle_get_report(self, web3_integration):
        report = web3_integration.lido_contracts.lazy_oracle.get_latest_report_data()
        assert report is not None

    def test_get_vaults(self, web3_integration):
        vaults = web3_integration.lido_contracts.lazy_oracle.get_all_vaults()
        assert len(vaults) != 0

    def test_get_slashing_reserve(self, web3_integration):
        slashing_reserve = web3_integration.lido_contracts.oracle_daemon_config.slashing_reserve_we_right_shift()
        assert slashing_reserve != 0
