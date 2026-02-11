from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber

from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import (
    BadDebtSocializedEventFactory,
    BadDebtWrittenOffEventFactory,
    BurnedSharesEventFactory,
    MerkleValueFactory,
    MintedSharesEventFactory,
    VaultAddresses,
    VaultConnectedEventFactory,
    VaultFeesUpdatedEventFactory,
    VaultRebalancedEventFactory,
)

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestBuildPrevReportMaps:

    def test_no_prev_report(self):
        prev_fee_map, prev_liability_shares_map = StakingVaultsService._build_prev_report_maps(None)

        assert prev_fee_map[VaultAddresses.VAULT_0] == 0
        assert prev_liability_shares_map[VaultAddresses.VAULT_0] == 0

    def test_empty_prev_report_values(self):
        prev_report = MagicMock()
        prev_report.values = []

        prev_fee_map, prev_liability_shares_map = StakingVaultsService._build_prev_report_maps(prev_report)

        assert prev_fee_map[VaultAddresses.VAULT_1] == 0
        assert prev_liability_shares_map[VaultAddresses.VAULT_1] == 0

    def test_with_prev_report(self):
        vault_0 = MerkleValueFactory.build(vault_address=VaultAddresses.VAULT_0, fee=111, liability_shares=222)
        vault_1 = MerkleValueFactory.build(vault_address=VaultAddresses.VAULT_1, fee=333, liability_shares=444)
        prev_report = MagicMock()
        prev_report.values = [vault_0, vault_1]

        prev_fee_map, prev_liability_shares_map = StakingVaultsService._build_prev_report_maps(prev_report)

        assert prev_fee_map[VaultAddresses.VAULT_0] == 111
        assert prev_fee_map[VaultAddresses.VAULT_1] == 333
        assert prev_liability_shares_map[VaultAddresses.VAULT_0] == 222
        assert prev_liability_shares_map[VaultAddresses.VAULT_1] == 444
        assert set(prev_fee_map.keys()) == {VaultAddresses.VAULT_0, VaultAddresses.VAULT_1}
        assert set(prev_liability_shares_map.keys()) == {VaultAddresses.VAULT_0, VaultAddresses.VAULT_1}


@pytest.mark.unit
class TestGetVaultEventsForFees:

    @pytest.fixture
    def vault_hub_mock(self):
        mock = MagicMock()
        mock.get_vault_fee_updated_events = MagicMock(return_value=[])
        mock.get_minted_events = MagicMock(return_value=[])
        mock.get_burned_events = MagicMock(return_value=[])
        mock.get_vault_rebalanced_events = MagicMock(return_value=[])
        mock.get_bad_debt_socialized_events = MagicMock(return_value=[])
        mock.get_bad_debt_written_off_to_be_internalized_events = MagicMock(return_value=[])
        mock.get_vault_connected_events = MagicMock(return_value=[])
        return mock

    def test_groups_events_and_tracks_connected_vaults(self, web3, vault_hub_mock):
        # Setup
        from_block = BlockNumber(1)
        to_block = BlockNumber(100)

        fee_updated_event = VaultFeesUpdatedEventFactory.build(vault=VaultAddresses.VAULT_0)
        minted_event = MintedSharesEventFactory.build(vault=VaultAddresses.VAULT_1)
        burned_event = BurnedSharesEventFactory.build(vault=VaultAddresses.VAULT_1)
        rebalanced_event = VaultRebalancedEventFactory.build(vault=VaultAddresses.VAULT_2)
        written_off_event = BadDebtWrittenOffEventFactory.build(vault=VaultAddresses.VAULT_2)
        socialized_event = BadDebtSocializedEventFactory.build(
            vault_donor=VaultAddresses.VAULT_0,
            vault_acceptor=VaultAddresses.VAULT_3,
        )
        connected_event = VaultConnectedEventFactory.build(vault=VaultAddresses.VAULT_3)

        vault_hub_mock.get_vault_fee_updated_events.return_value = [fee_updated_event]
        vault_hub_mock.get_minted_events.return_value = [minted_event]
        vault_hub_mock.get_burned_events.return_value = [burned_event]
        vault_hub_mock.get_vault_rebalanced_events.return_value = [rebalanced_event]
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events.return_value = [written_off_event]
        vault_hub_mock.get_bad_debt_socialized_events.return_value = [socialized_event]
        vault_hub_mock.get_vault_connected_events.return_value = [connected_event]

        service = StakingVaultsService(web3)

        # Act
        events, connected_vaults = service._get_vault_events_for_fees(vault_hub_mock, from_block, to_block)

        # Assert
        vault_hub_mock.get_vault_fee_updated_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_minted_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_burned_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_vault_rebalanced_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_bad_debt_written_off_to_be_internalized_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_bad_debt_socialized_events.assert_called_once_with(from_block, to_block)
        vault_hub_mock.get_vault_connected_events.assert_called_once_with(from_block, to_block)

        assert fee_updated_event in events[VaultAddresses.VAULT_0]
        assert minted_event in events[VaultAddresses.VAULT_1]
        assert burned_event in events[VaultAddresses.VAULT_1]
        assert rebalanced_event in events[VaultAddresses.VAULT_2]
        assert written_off_event in events[VaultAddresses.VAULT_2]
        assert socialized_event in events[VaultAddresses.VAULT_0]
        assert socialized_event in events[VaultAddresses.VAULT_3]
        assert connected_event in events[VaultAddresses.VAULT_3]
        assert VaultAddresses.VAULT_3 in connected_vaults
