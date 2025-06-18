import logging

from src.modules.accounting.events import (
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultFeesUpdatedEvent,
)
from src.providers.execution.base_interface import ContractInterface

logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    def get_minted_events(self, from_block_number: int, to_block_number: int) -> list:
        return []

        # logs = self.events.MintedSharesOnVault().get_logs(
        #     from_block=from_block_number,
        #     to_block=to_block_number
        # )

        # if not logs:
        #     return []

        # events: list[MintedSharesOnVaultEvent] = []
        # for log in logs:
        #     parsed_log = self.events.MintedSharesOnVault().process_log(log)
        #     events.append(MintedSharesOnVaultEvent.from_log(parsed_log))

        # return events

    def get_burned_events(self, from_block_number: int, to_block_number: int) -> list:
        return []

        # logs = self.events.BurnedSharesOnVault().get_logs(
        #     from_block=from_block_number,
        #     to_block=to_block_number
        # )

        # if not logs:
        #     return []

        # events: list[BurnedSharesOnVaultEvent] = []
        # for log in logs:
        #     parsed_log = self.events.BurnedSharesOnVault().process_log(log)
        #     events.append(BurnedSharesOnVaultEvent.from_log(parsed_log))

        # return events

    def get_vaults_fee_updated_events(self, from_block_number: int, to_block_number: int) -> list:
        return []
        # logs = self.events.VaultFeesUpdated().get_logs(
        #     from_block=from_block_number,
        #     to_block=to_block_number
        # )

        # if not logs:
        #     return []

        # events: list[VaultFeesUpdatedEvent] = []
        # for log in logs:
        #     parsed_log = self.events.VaultFeesUpdated().process_log(log)
        #     events.append(VaultFeesUpdatedEvent.from_log(parsed_log))

        # return events