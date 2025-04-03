import json
import logging
from dataclasses import asdict, dataclass
from typing import List, cast, Any

from eth_typing import ChecksumAddress
from oz_merkle_tree import StandardMerkleTree
from web3 import Web3
from web3.module import Module

from src.modules.accounting.types import VaultData, VaultsData, VaultsMap, VaultTreeNode
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import Validator
from src.providers.execution.contracts.staking_vault import StakingVaultContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import CID, MultiIPFSProvider
from src.types import BlockStamp

logger = logging.getLogger(__name__)


@dataclass
class VaultProof:
    id: int
    valuationWei: int
    inOutDelta: int
    fee: int
    sharesMinted: int
    leaf: str
    proof: List[str]


VaultToValidators = dict[ChecksumAddress, list[Validator]]


class StakingVaults(Module):
    w3: Web3
    ipfs_client: MultiIPFSProvider
    cl: ConsensusClient
    vault_hub: VaultHubContract

    def __init__(self, w3: Web3, cl: ConsensusClient, ipfs: MultiIPFSProvider, vault_hub: VaultHubContract) -> None:
        super().__init__(w3)

        self.w3 = w3
        self.ipfs_client = ipfs
        self.cl = cl
        self.vault_hub = vault_hub

    def _load_vault(self, address: ChecksumAddress) -> StakingVaultContract:
        return cast(
            StakingVaultContract,
            self.w3.eth.contract(
                address=address,
                ContractFactoryClass=StakingVaultContract,
                decode_tuples=True,
            ),
        )

    def get_vaults(self, blockstamp: BlockStamp) -> VaultsMap:
        vault_count = self.vault_hub.get_vaults_count(blockstamp)
        pending_deposits = self.cl.get_pending_deposits(blockstamp)
        deposit_map = dict[str, int]()

        for deposit in pending_deposits:
            if deposit.withdrawal_credentials not in deposit_map:
                deposit_map[deposit.withdrawal_credentials] = 0

            deposit_map[deposit.withdrawal_credentials] += Web3.to_wei(int(deposit.amount), 'gwei')

        vaults = VaultsMap()
        for vault_ind in range(vault_count):
            vault_socket = self.vault_hub.vault_socket(vault_ind, blockstamp)

            balance_wei = self.w3.eth.get_balance(
                self.w3.to_checksum_address(vault_socket.vault), block_identifier=blockstamp.block_hash
            )

            vault = self._load_vault(vault_socket.vault)
            vault_in_out_delta = vault.in_out_delta(blockstamp)
            print(vault_in_out_delta)
            vault_withdrawal_credentials = vault.withdrawal_credentials(blockstamp)
            print(vault_withdrawal_credentials)

            pending_deposit = 0
            if vault_withdrawal_credentials in deposit_map:
                pending_deposit = deposit_map[vault_withdrawal_credentials]

            fee = 0
            vaults[vault_socket.vault] = VaultData(
                vault_ind,
                balance_wei,
                vault_in_out_delta,
                vault_socket.shares_minted,
                fee,
                pending_deposit,
                vault_socket.vault,
                vault_withdrawal_credentials,
                vault_socket,
            )

        return vaults

    @staticmethod
    def connect_vault_to_validators(validators: list[Validator], vault_addresses: VaultsMap) -> VaultToValidators:
        wc_vault_map = dict[str, VaultData]()
        for vault_pk in vault_addresses:
            wc_vault_map[vault_addresses[vault_pk].withdrawal_credentials] = vault_addresses[vault_pk]

        result = VaultToValidators()
        for validator in validators:
            if validator.validator.withdrawal_credentials in wc_vault_map:
                vault = wc_vault_map[validator.validator.withdrawal_credentials]

                if vault.address not in result:
                    result[vault.address] = [validator]
                else:
                    result[vault.address].append(validator)

        return result

    @staticmethod
    def get_merkle_tree(data: list[VaultTreeNode]) -> StandardMerkleTree:
        return StandardMerkleTree(data, ("address", "uint256", "uint256", "uint256", "uint256"))

    @staticmethod
    def get_vault_to_proof_map(merkle_tree: StandardMerkleTree, vaults: VaultsMap) -> dict[str, VaultProof]:
        result = {}
        for v in merkle_tree.values:
            vault_address = v["value"][0]
            vault_valuation_wei = v["value"][1]
            vault_in_out_delta = v["value"][2]
            vault_fee = v["value"][3]
            vault_shares_minted = v["value"][4]

            leaf = f"0x{merkle_tree.leaf(v["value"]).hex()}"
            proof = []
            for elem in merkle_tree.get_proof(v["treeIndex"]):
                proof.append(f"0x{elem.hex()}")

            result[vault_address] = VaultProof(
                id=vaults[vault_address].vault_ind,
                valuationWei=vault_valuation_wei,
                inOutDelta=vault_in_out_delta,
                fee=vault_fee,
                sharesMinted=vault_shares_minted,
                leaf=leaf,
                proof=proof,
            )

        return result

    def get_vaults_data(self, validators: list[Validator], blockstamp: BlockStamp) -> VaultsData:
        vaults = self.get_vaults(blockstamp)
        vaults_validators = StakingVaults.connect_vault_to_validators(validators, vaults)

        vaults_values = [0] * len(vaults)
        vaults_net_cash_flows = [0] * len(vaults)
        tree_data: list[VaultTreeNode] = [('', 0, 0, 0, 0) for _ in range(len(vaults))]

        for vault_address in vaults:
            vault = vaults[vault_address]

            vaults_values[vault.vault_ind] = vault.balance_wei + vault.pending_deposit
            vaults_net_cash_flows[vault.vault_ind] = vault.in_out_delta

            if vault_address in vaults_validators:
                vault_validators = vaults_validators[vault_address]

                vault_cl_balance_wei = 0
                for validator in vault_validators:
                    vault_cl_balance_wei += Web3.to_wei(int(validator.balance), 'gwei')

                vaults_values[vault.vault_ind] += vault_cl_balance_wei

            tree_data[vault.vault_ind] = (
                vault_address,
                vaults_values[vault.vault_ind],
                vault.in_out_delta,
                vault.fee,
                vault.shares_minted,
            )

            logger.info(
                {
                    'msg': f'Vault values for vault: {vault.address}.',
                    'vault_in_out_delta': vault.in_out_delta,
                    'vault_value': vaults_values[vault.vault_ind],
                }
            )

        return vaults_values, vaults_net_cash_flows, tree_data, vaults

    def publish_proofs(self, tree: StandardMerkleTree, bs: BlockStamp, vaults: VaultsMap) -> CID:
        data = self.get_vault_to_proof_map(tree, vaults)

        def encoder(o):
            if hasattr(o, "__dataclass_fields__"):
                return asdict(o)
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        result: dict[str, Any] = {
            "merkleTreeRoot": f"0x{tree.root.hex()}",
            "refSlot": bs.slot_number,
            "proofs": data,
            "block_number": bs.block_number,
        }

        dumped_proofs = json.dumps(result, default=encoder)
        print(dumped_proofs)

        cid = self.ipfs_client.publish(dumped_proofs.encode('utf-8'), 'proofs.json')

        return cid

    def publish_tree(self, tree: StandardMerkleTree, bs: BlockStamp, proofs_cid: CID) -> CID:
        def encoder(o):
            if isinstance(o, bytes):
                return f"0x{o.hex()}"
            if isinstance(o, CID):
                return str(o)
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        output = {
            **dict(tree.dump()),
            "merkleTreeRoot": f"0x{tree.root.hex()}",
            "refSlof": bs.slot_number,
            "blockNumber": bs.block_number,
            "proofsCID": str(proofs_cid),
            "leafIndexToData": {
                "0": "vault_address",
                "1": "valuation_wei",
                "2": "in_out_delta",
                "3": "fee",
                "4": "shares_minted",
            },
        }

        dumped_tree_str = json.dumps(output, default=encoder)
        print(dumped_tree_str)

        cid = self.ipfs_client.publish(dumped_tree_str.encode('utf-8'), 'merkle_tree.json')

        return cid
