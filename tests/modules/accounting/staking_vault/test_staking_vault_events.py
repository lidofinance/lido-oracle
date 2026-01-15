"""
Event sorting related tests.
"""

import copy

import pytest
from eth_typing import BlockNumber

from src.modules.oracles.accounting.events import sort_events
from tests.modules.accounting.staking_vault.conftest import (
    BadDebtSocializedEventFactory,
    BurnedSharesEventFactory,
    MintedSharesEventFactory,
    VaultFeesUpdatedEventFactory,
    VaultRebalancedEventFactory,
)


class TestSortEvents:
    """Tests for sort_events function."""

    @pytest.mark.unit
    def test_sort_events_in_reverse_order(self):
        """Test that events are sorted in reverse chronological order."""
        vault_adr = 'vault1_adr'

        events = [
            MintedSharesEventFactory.build(vault=vault_adr, block_number=BlockNumber(3_600), log_index=1),
            BurnedSharesEventFactory.build(vault=vault_adr, block_number=BlockNumber(3_600), log_index=3),
            VaultFeesUpdatedEventFactory.build(vault=vault_adr, block_number=BlockNumber(3_601), log_index=0),
            VaultRebalancedEventFactory.build(vault=vault_adr, block_number=BlockNumber(3_599), log_index=7),
            BadDebtSocializedEventFactory.build(
                vault_donor=vault_adr, vault_acceptor='vault2', block_number=BlockNumber(3_600), log_index=2
            ),
        ]

        expected_order = [
            (3_601, 0),
            (3_600, 3),
            (3_600, 2),
            (3_600, 1),
            (3_599, 7),
        ]

        # copy expected to avoid accidental mutation
        expected = [copy.copy(events[idx]) for idx in [2, 1, 4, 0, 3]]

        sort_events(events)

        assert [(event.block_number, event.log_index) for event in events] == expected_order
        for actual, exp in zip(events, expected, strict=True):
            assert actual.block_number == exp.block_number
            assert actual.log_index == exp.log_index
