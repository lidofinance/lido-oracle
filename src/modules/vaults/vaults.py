import json
from typing import Protocol, List

from web3.contract.contract import ContractFunction

from src.providers.consensus.types import Validator
from src.providers.ipfs import IPFSProvider, CID
from src.types import BlockStamp
from src.web3py.types import Web3
from oz_merkle_tree import StandardMerkleTree
from dataclasses import dataclass, asdict


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
                validator.validator.effective_balance = validator.validator.effective_balance * 10 ** 9

            result[vault_address].validators = validators[vault_address]

    return result


class Vaults:
    def __init__(self, vault_runner: VaultRunner, cl: ClClient, w3: Web3, ipfs_client: IPFSProvider):
        self.vault_runner = vault_runner
        self.cl = cl
        self.w3 = w3
        self.ipfs_client = ipfs_client

    def handle(self, bs: BlockStamp):
        # TODO
        #  get_prev_merkle_root from blockchain
        #  by hash - get from ipfs prev report

        vaults_to_balance = self.get_vault_addresses()
        vaults_to_validators = self.get_validators(bs, vaults_to_balance)

        vaults_valuation = get_vaults_valuation(vaults_to_balance, vaults_to_validators)
        merkle_tree = get_merkle_tree(vaults_valuation)

        proofs_cid = self.publish_proofs(merkle_tree, bs, vaults_to_balance, vaults_to_validators)
        print(proofs_cid)

        tree_cid = self.publish_tree(merkle_tree, bs, proofs_cid)
        print(tree_cid)

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

    def publish_tree(self, tree: StandardMerkleTree, bs: BlockStamp, proofs_cid: CID) -> CID:
        def encoder(o):
            if isinstance(o, bytes):
                return f"0x{o.hex()}"
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        dumped_tree = tree.dump()
        dumped_tree.update({
            "merkleTreeRoot": f"0x{tree.root.hex()}",
            "refSlof": bs.slot_number,
            "proofsCID": str(proofs_cid)
        })

        dumped_tree_str = json.dumps(dumped_tree, default=encoder)

        cid = self.ipfs_client.publish(dumped_tree_str.encode('utf-8'), 'merkle_tree.json')

        return cid

    def publish_proofs(self, tree: StandardMerkleTree, bs: BlockStamp, vaults_to_balance: VaultToBalanceWeiMap, vaults_to_validators: VaultToValidatorsMap) -> CID:
        data = get_vault_to_proof_map(tree, vaults_to_balance, vaults_to_validators)

        def encoder(o):
            if hasattr(o, "__dataclass_fields__"):
                return asdict(o)
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        result = dict()
        result['merkleTreeRoot'] = f"0x{tree.root.hex()}"
        result['refSlot'] = bs.slot_number
        result['proofs'] = data

        dumped_proofs = json.dumps(result, default=encoder)

        cid = self.ipfs_client.publish(dumped_proofs.encode('utf-8'), 'proofs.json')

        return cid