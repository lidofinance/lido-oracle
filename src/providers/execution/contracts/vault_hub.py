import logging

from eth_typing import HexStr
from src.modules.accounting.events import MintedSharesOnVaultEvent, BurnedSharesOnVaultEvent, VaultFeesUpdatedEvent
from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class VaultHubContract(ContractInterface):
    abi_path = './assets/VaultHub.json'

    def get_minted_events(self, from_block_number: int, to_block_number: int) -> list[MintedSharesOnVaultEvent]:
        logs = self.w3.eth.get_logs({
            "fromBlock": from_block_number,
            "toBlock": to_block_number,
            "address": self.address,
            "topics": [
                HexStr(self.w3.keccak(self.events.MintedSharesOnVaultEvent.signature).hex())
            ]
        })

        if not logs:
            return []

        events = []
        for log in logs:
            parsed_log = self.events.MintedSharesOnVault.process_log(log)
            events.append(MintedSharesOnVaultEvent.from_log(parsed_log))

        return events

    def get_burned_events(self, from_block_number: int, to_block_number: int) -> list[BurnedSharesOnVaultEvent]:
        logs = self.w3.eth.get_logs({
            "fromBlock": from_block_number,
            "toBlock": to_block_number,
            "address": self.address,
            "topics": [
                HexStr(self.w3.keccak(self.events.BurnedSharesOnVaultEvent.signature).hex())
            ]
        })

        if not logs:
            return []

        events = []
        for log in logs:
            parsed_log = self.events.BurnedSharesOnVaultEvent.process_log(log)
            events.append(BurnedSharesOnVaultEvent.from_log(parsed_log))

        return events

    def get_vaults_fee_updated_events(self, from_block_number: int, to_block_number: int) -> list[VaultFeesUpdatedEvent]:
        logs = self.w3.eth.get_logs({
                "fromBlock": from_block_number,
                "toBlock": to_block_number,
                "address": self.address,
                "topics": [
                    HexStr(self.w3.keccak(self.events.VaultFeesUpdatedEvent.signature).hex())
                ]
            })

        if not logs:
            return []

        events = []
        for log in logs:
            parsed_log = self.events.VaultFeesUpdatedEvent.process_log(log)
            events.append(VaultFeesUpdatedEvent.from_log(parsed_log))

        return events