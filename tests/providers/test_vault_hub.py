import pytest
from web3.exceptions import Web3Exception


@pytest.mark.testnet
@pytest.mark.integration
class TestVaultHubSmoke:

    def test_get_burned_events(self, web3_integration):
        try:
            events = web3_integration.lido_contracts.vault_hub.get_burned_events(634086 - 1_000, 634086)

            assert len(events) != 0
        except Web3Exception as e:
            print(f"Error: {e}")

    def test_get_minted_events(self, web3_integration):
        try:
            events = web3_integration.lido_contracts.vault_hub.get_minted_events(634086 - 1_000, 634086)

            assert len(events) != 0
        except Web3Exception as e:
            print(f"Error: {e}")

    def test_get_updated_events(self, web3_integration):
        try:
            events = web3_integration.lido_contracts.vault_hub.get_vault_fee_updated_events(634086 - 1_000, 634_086)

            assert len(events) == 0
        except Web3Exception as e:
            print(f"Error: {e}")
