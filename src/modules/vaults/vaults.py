from typing import Protocol, List

from web3.contract.contract import ContractFunction
from src.providers.consensus.types import Validator
from src.types import BlockStamp
from src.web3py.types import Web3
from oz_merkle_tree import StandardMerkleTree
from dataclasses import dataclass


class VaultRunner(Protocol):
    def vaultsCount(self) -> ContractFunction:
        ...

    def vault(self, vault_index: int) -> ContractFunction:
        ...

class ClClient(Protocol):
    def get_validators_no_cache(self, blockstamp: BlockStamp) -> list[Validator]:
        ...

VaultToValidatorsMap = dict[str, List[Validator]]
VaultToBalanceWeiMap = dict[str, int]

@dataclass
class VaultProof:
    valuationWei: int
    vaultBalanceWei: int
    leaf: str
    proof: List[str]
    validators: List[Validator]

def get_vaults_valuation(vault_addresses: VaultToBalanceWeiMap, validators: VaultToValidatorsMap) -> VaultToBalanceWeiMap:
    result = VaultToBalanceWeiMap()
    for vault_address, vault_balance in vault_addresses.items():
        result[vault_address] = vault_balance

        if validators.get(vault_address) is not None:
            for validator in validators[vault_address]:
                result[vault_address] += validator.balance * 10 ** 9

    return result

def get_merkle_tree(data: VaultToBalanceWeiMap) -> StandardMerkleTree:
    return StandardMerkleTree(tuple(data.items()), ("address", "uint256"))


def get_vault_to_proof_map(merkle_tree: StandardMerkleTree, vaults: VaultToBalanceWeiMap, validators: VaultToValidatorsMap) -> dict[str, VaultProof]:
    result = dict()
    for v in merkle_tree.values:
        vault_address = v["value"][0]
        valuation_wei = v["value"][1]

        leaf = f"0x{merkle_tree.leaf(v["value"]).hex()}"
        proof = []
        for elem in merkle_tree.get_proof(v["treeIndex"]):
            proof.append(f"0x{elem.hex()}")

        result[vault_address] = VaultProof(
            valuationWei=valuation_wei,
            vaultBalanceWei=vaults[vault_address],
            leaf=leaf,
            proof=proof,
            validators=[]
        )
        if validators.get(vault_address) is not None:
            for validator in validators[vault_address]:
                validator.balance = validator.balance * 10 ** 9

            result[vault_address].validators = validators[vault_address]

    return result


class Vaults:
    def __init__(self, vault_runner: VaultRunner, cl: ClClient, w3: Web3):
        self.vault_runner = vault_runner
        self.cl = cl
        self.w3 = w3

    def get_vault_addresses(self) -> VaultToBalanceWeiMap:
        vault_count =  self.vault_runner.vaultsCount().call()

        addresses = VaultToBalanceWeiMap()
        for i in range(vault_count):
            vault_address = str.lower(self.vault_runner.vault(i).call())
            balance_wei = self.w3.eth.get_balance(self.w3.to_checksum_address(vault_address))
            addresses[vault_address] = balance_wei
        return addresses

    def get_validators(self, block: BlockStamp, vault_addresses: VaultToBalanceWeiMap) -> VaultToValidatorsMap:
        validators = self.cl.get_validators_no_cache(block)

        result = VaultToValidatorsMap()
        for validator in validators:
           vault_adr = '0x' + validator.validator.withdrawal_credentials[-40:].lower()
           if vault_adr in vault_addresses:
                if vault_adr not in result:
                    result[vault_adr] = [validator]
                else:
                    result[vault_adr].append(validator)

        return result