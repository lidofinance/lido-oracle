import logging

from eth_typing import BlockNumber

from src.modules.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultConnectedEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
)
from src.providers.execution.base_interface import ContractInterface
from src.utils.events import get_events_in_range

logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    def get_minted_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[MintedSharesOnVaultEvent]:
        logs = get_events_in_range(self.events.MintedSharesOnVault(), from_block_number, to_block_number)

        return [MintedSharesOnVaultEvent.from_log(log) for log in logs]

    def get_burned_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[BurnedSharesOnVaultEvent]:
        logs = get_events_in_range(self.events.BurnedSharesOnVault(), from_block_number, to_block_number)

        return [BurnedSharesOnVaultEvent.from_log(log) for log in logs]

    def get_vault_fee_updated_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[VaultFeesUpdatedEvent]:
        logs = get_events_in_range(self.events.VaultFeesUpdated(), from_block_number, to_block_number)

        return [VaultFeesUpdatedEvent.from_log(log) for log in logs]

    def get_vault_rebalanced_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[VaultRebalancedEvent]:
        logs = get_events_in_range(self.events.VaultRebalanced(), from_block_number, to_block_number)

        return [VaultRebalancedEvent.from_log(log) for log in logs]

    def get_bad_debt_socialized_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[BadDebtSocializedEvent]:
        logs = get_events_in_range(self.events.BadDebtSocialized(), from_block_number, to_block_number)

        return [BadDebtSocializedEvent.from_log(log) for log in logs]

    def get_bad_debt_written_off_to_be_internalized_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[BadDebtWrittenOffToBeInternalizedEvent]:
        logs = get_events_in_range(self.events.BadDebtWrittenOffToBeInternalized(), from_block_number, to_block_number)

        return [BadDebtWrittenOffToBeInternalizedEvent.from_log(log) for log in logs]

    def get_vault_connected_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[VaultConnectedEvent]:
        logs = get_events_in_range(self.events.VaultConnected(), from_block_number, to_block_number)

        return [VaultConnectedEvent.from_log(log) for log in logs]
