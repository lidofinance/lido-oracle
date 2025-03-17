from typing import Protocol, List

from web3.contract.contract import ContractFunction
from src.providers.consensus.types import Validator
from src.types import BlockStamp


class VaultRunner(Protocol):
    def vaultsCount(self) -> ContractFunction:
        ...

class ClClient(Protocol):
    def get_validators_no_cache(self, blockstamp: BlockStamp) -> list[Validator]:
        ...

class Vaults:
    def __init__(self, vault_runner: VaultRunner, cl: ClClient):
        self.vault_runner = vault_runner
        self.cl = cl

    def get_valuation(self) -> int:
        return self.vault_runner.vaultsCount().call()

    def get_validators(self, block: BlockStamp) -> List[Validator]:
        validators = self.cl.get_validators_no_cache(block)

        vault_validators = []
        needed_wc = '0x00471c0a4629eec7d52fde33ea098f8b90a1651e2b5e45742d404dd3bb3ad4c5'
        for validator in validators:
            if validator.validator.withdrawal_credentials == needed_wc:
                vault_validators.append(validator)

        return vault_validators
