import logging

from eth_typing import HexStr
from web3.types import BlockIdentifier

from src.modules.accounting.events import MintedSharesOnVaultEvent, BurnedSharesOnVaultEvent, VaultFeesUpdatedEvent
from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    def get_vaults_count(self, block_identifier: BlockIdentifier = 'latest') -> int:
        """
        Returns the number of vaults attached to the VaultHub.
        """
        response = self.functions.vaultsCount().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `vaultsCount().',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )

        return response

    def get_minted_events(self, from_block_number: int, to_block_number: int) -> list:
        logs = self.w3.eth.get_logs({
            "fromBlock": from_block_number,
            "toBlock": to_block_number,
            "address": self.address,
            "topics": [
                HexStr(self.w3.keccak(self.events.MintedSharesOnVault.signature).hex())
            ]
        })

        if not logs:
            return []

        events: list[MintedSharesOnVaultEvent] = []
        for log in logs:
            parsed_log = self.events.MintedSharesOnVault.process_log(log)
            events.append(MintedSharesOnVaultEvent.from_log(parsed_log))

        return events

    def get_burned_events(self, from_block_number: int, to_block_number: int) -> list:
        logs = self.w3.eth.get_logs({
            "fromBlock": from_block_number,
            "toBlock": to_block_number,
            "address": self.address,
            "topics": [
                HexStr(self.w3.keccak(self.events.BurnedSharesOnVault.signature).hex())
            ]
        })

        if not logs:
            return []

        events: list[BurnedSharesOnVaultEvent] = []
        for log in logs:
            parsed_log = self.events.BurnedSharesOnVault.process_log(log)
            events.append(BurnedSharesOnVaultEvent.from_log(parsed_log))

        return events

    def get_vaults_fee_updated_events(self, from_block_number: int, to_block_number: int) -> list:
        logs = self.w3.eth.get_logs({
                "fromBlock": from_block_number,
                "toBlock": to_block_number,
                "address": self.address,
                "topics": [
                    HexStr(self.w3.keccak(self.events.VaultFeesUpdated.signature).hex())
                ]
            })

        if not logs:
            return []

        events: list[VaultFeesUpdatedEvent] = []
        for log in logs:
            parsed_log = self.events.VaultFeesUpdated.process_log(log)
            events.append(VaultFeesUpdatedEvent.from_log(parsed_log))

        return events