import logging

from src.modules.accounting.events import MintedSharesOnVaultEvent, BurnedSharesOnVaultEvent, VaultFeesUpdatedEvent
from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    def get_minted_events(self, from_block_number: int, to_block_number: int) -> list:
        logs = self.events.MintedSharesOnVault().get_logs(
            from_block=from_block_number,
            to_block=to_block_number
        )

        if not logs:
            return []

        events: list[MintedSharesOnVaultEvent] = []
        for log in logs:
            events.append(MintedSharesOnVaultEvent.from_log(log))

        return events

    def get_burned_events(self, from_block_number: int, to_block_number: int) -> list:
        logs = self.events.BurnedSharesOnVault().get_logs(
            from_block=from_block_number,
            to_block=to_block_number
        )

        if not logs:
            return []

        events: list[BurnedSharesOnVaultEvent] = []
        for log in logs:
            events.append(BurnedSharesOnVaultEvent.from_log(log))

        return events

    def get_vaults_fee_updated_events(self, from_block_number: int, to_block_number: int) -> list:
        logs = self.events.VaultFeesUpdated().get_logs(
            from_block=from_block_number,
            to_block=to_block_number
        )

        if not logs:
            return []

        events: list[VaultFeesUpdatedEvent] = []
        for log in logs:
            events.append(VaultFeesUpdatedEvent.from_log(log))

        return events