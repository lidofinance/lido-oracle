import logging

from eth_typing import BlockNumber

from modules.oracles.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultConnectedEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
)
from providers.execution.base_interface import ContractInterface
from utils.events import get_events_in_range


logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    def get_minted_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[MintedSharesOnVaultEvent]:
        logger.info(
            {'msg': f'Call `MintedSharesOnVault` events [{from_block_number}:{to_block_number}].', 'to': self.address}
        )
        logs = get_events_in_range(self.events.MintedSharesOnVault(), from_block_number, to_block_number)

        return [MintedSharesOnVaultEvent.from_log(log) for log in logs]

    def get_burned_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[BurnedSharesOnVaultEvent]:
        logger.info(
            {'msg': f'Call `BurnedSharesOnVault` events [{from_block_number}:{to_block_number}].', 'to': self.address}
        )
        logs = get_events_in_range(self.events.BurnedSharesOnVault(), from_block_number, to_block_number)

        return [BurnedSharesOnVaultEvent.from_log(log) for log in logs]

    def get_vault_fee_updated_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[VaultFeesUpdatedEvent]:
        logger.info(
            {'msg': f'Call `VaultFeesUpdated` events [{from_block_number}:{to_block_number}].', 'to': self.address}
        )
        logs = get_events_in_range(self.events.VaultFeesUpdated(), from_block_number, to_block_number)

        return [VaultFeesUpdatedEvent.from_log(log) for log in logs]

    def get_vault_rebalanced_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[VaultRebalancedEvent]:
        logger.info(
            {'msg': f'Call `VaultRebalanced` events [{from_block_number}:{to_block_number}].', 'to': self.address}
        )
        logs = get_events_in_range(self.events.VaultRebalanced(), from_block_number, to_block_number)

        return [VaultRebalancedEvent.from_log(log) for log in logs]

    def get_bad_debt_socialized_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[BadDebtSocializedEvent]:
        logger.info(
            {'msg': f'Call `BadDebtSocialized` events [{from_block_number}:{to_block_number}].', 'to': self.address}
        )
        logs = get_events_in_range(self.events.BadDebtSocialized(), from_block_number, to_block_number)

        return [BadDebtSocializedEvent.from_log(log) for log in logs]

    def get_bad_debt_written_off_to_be_internalized_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[BadDebtWrittenOffToBeInternalizedEvent]:
        logger.info(
            {
                'msg': f'Call `BadDebtWrittenOffToBeInternalized` events [{from_block_number}:{to_block_number}].',
                'to': self.address,
            }
        )
        logs = get_events_in_range(self.events.BadDebtWrittenOffToBeInternalized(), from_block_number, to_block_number)

        return [BadDebtWrittenOffToBeInternalizedEvent.from_log(log) for log in logs]

    def get_vault_connected_events(
        self, from_block_number: BlockNumber, to_block_number: BlockNumber
    ) -> list[VaultConnectedEvent]:
        logger.info(
            {'msg': f'Call `VaultConnected` events [{from_block_number}:{to_block_number}].', 'to': self.address}
        )
        logs = get_events_in_range(self.events.VaultConnected(), from_block_number, to_block_number)

        return [VaultConnectedEvent.from_log(log) for log in logs]
