import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import List, cast, Any

from eth_typing import ChecksumAddress
from oz_merkle_tree import StandardMerkleTree
from web3 import Web3
from web3.module import Module

from src.modules.accounting.types import VaultData, VaultsData, VaultsMap, VaultTreeNode, LatestReportData
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import Validator, PendingDeposit
from src.providers.execution.contracts.staking_vault import StakingVaultContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import CID, MultiIPFSProvider
from src.types import BlockStamp
from src.utils.deposit_signature import is_valid_deposit_signature
from src.utils.types import hex_str_to_bytes

logger = logging.getLogger(__name__)


@dataclass
class VaultProof:
    id: int
    totalValueWei: int
    inOutDelta: int
    fee: int
    liabilityShares: int
    leaf: str
    proof: List[str]


VaultToValidators = dict[ChecksumAddress, list[Validator]]
VaultToPendingDeposits = dict[ChecksumAddress, list[PendingDeposit]]


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

    def get_vaults_data(
        self, validators: list[Validator], pending_deposits: list[PendingDeposit], blockstamp: BlockStamp
    ) -> VaultsData:
        vaults = self.get_vaults(blockstamp)
        if len(vaults) == 0:
            return [], {}

        vaults_validators = StakingVaults.connect_vault_to_validators(validators, vaults)
        vaults_pending_deposits = StakingVaults.connect_vault_to_pending_deposits(pending_deposits, vaults)

        vaults_values = [0] * len(vaults)
        tree_data: list[VaultTreeNode] = [('', 0, 0, 0, 0) for _ in range(len(vaults))]

        for vault_address, vault in vaults.items():
            vaults_values[vault.vault_ind] = vault.balance_wei

            if vault_address in vaults_validators:
                vault_validators = vaults_validators[vault_address]

                vault_cl_balance_wei = 0
                for validator in vault_validators:
                    vault_cl_balance_wei += Web3.to_wei(int(validator.balance), 'gwei')

                vaults_values[vault.vault_ind] += vault_cl_balance_wei

            if vault_address in vaults_pending_deposits:
                pending_deposits = vaults_pending_deposits[vault_address]
                vault_validator_pubkeys = set(
                    validator.validator.pubkey for validator in vaults_validators[vault_address]
                )

                deposits_by_pubkey: dict[str, list[PendingDeposit]] = defaultdict(list)
                for deposit in pending_deposits:
                    deposits_by_pubkey[deposit.pubkey].append(deposit)

                for pubkey, deposits in deposits_by_pubkey.items():
                    for deposit in (
                        deposits if pubkey in vault_validator_pubkeys else StakingVaults.filter_valid_deposits(deposits)
                    ):
                        vaults_values[vault.vault_ind] += Web3.to_wei(int(deposit.amount), 'gwei')

            tree_data[vault.vault_ind] = (
                vault_address,
                vaults_values[vault.vault_ind],
                vault.in_out_delta,
                vault.fee,
                vault.liability_shares,
            )

            logger.info(
                {
                    'msg': f'Vault values for vault: {vault.address}.',
                    'vault_in_out_delta': vault.in_out_delta,
                    'vault_value': vaults_values[vault.vault_ind],
                }
            )

        return tree_data, vaults

    def get_vaults(self, blockstamp: BlockStamp) -> VaultsMap:
        vaults = self.vault_hub.get_all_vaults(block_identifier=blockstamp.block_number)
        if len(vaults) == 0:
            return {}

        out = VaultsMap()
        for vault_ind in range(len(vaults)):
            vault = vaults[vault_ind]
            fee = 0

            out[vault.vault] = VaultData(
                vault_ind,
                vault.balance,
                vault.in_out_delta,
                vault.liability_shares,
                fee,
                vault.vault,
                vault.withdrawal_credentials,
            )

        return out

    @staticmethod
    def connect_vault_to_validators(validators: list[Validator], vault_addresses: VaultsMap) -> VaultToValidators:
        wc_vault_map: dict[str, VaultData] = {
            vault_data.withdrawal_credentials: vault_data for vault_data in vault_addresses.values()
        }

        result: VaultToValidators = defaultdict(list)
        for validator in validators:
            wc = validator.validator.withdrawal_credentials

            if wc in wc_vault_map:
                vault = wc_vault_map[validator.validator.withdrawal_credentials]
                result[vault.address].append(validator)

        return result

    @staticmethod
    def connect_vault_to_pending_deposits(
        pending_deposits: list[PendingDeposit], vault_addresses: VaultsMap
    ) -> VaultToPendingDeposits:
        wc_vault_map: dict[str, VaultData] = {
            vault_data.withdrawal_credentials: vault_data for vault_data in vault_addresses.values()
        }

        result: VaultToPendingDeposits = defaultdict(list)
        for deposit in pending_deposits:
            wc = deposit.withdrawal_credentials

            if wc in wc_vault_map:
                vault = wc_vault_map[deposit.withdrawal_credentials]
                result[vault.address].append(deposit)

        return result

    @staticmethod
    def filter_valid_deposits(deposits: list[PendingDeposit]) -> list[PendingDeposit]:
        """
        Validates deposit signatures and returns a list of valid deposits.
        Once a valid pending deposit is found, all subsequent deposits are considered valid.
        """
        valid_deposits = []
        valid_found = False

        for deposit in deposits:
            # If we've already found a valid pending deposit, accept all subsequent ones
            if valid_found:
                valid_deposits.append(deposit)
                continue

            # Verify the deposit signature
            is_valid = is_valid_deposit_signature(
                pubkey=hex_str_to_bytes(deposit.pubkey),
                withdrawal_credentials=hex_str_to_bytes(deposit.withdrawal_credentials),
                amount_gwei=deposit.amount,
                signature=hex_str_to_bytes(deposit.signature),
            )

            if not is_valid:
                logger.warning(
                    {
                        'msg': f'Invalid deposit signature for deposit: {deposit}.',
                    }
                )
                continue

            # Mark that we found a valid deposit and include it
            valid_found = True
            valid_deposits.append(deposit)

        return valid_deposits

    @staticmethod
    def get_merkle_tree(data: list[VaultTreeNode]) -> StandardMerkleTree:
        return StandardMerkleTree(data, ("address", "uint256", "uint256", "uint256", "uint256"))

    @staticmethod
    def get_vault_to_proof_map(merkle_tree: StandardMerkleTree, vaults: VaultsMap) -> dict[str, VaultProof]:
        result = {}
        for v in merkle_tree.values:
            vault_address = v["value"][0]
            vault_total_value_wei = v["value"][1]
            vault_in_out_delta = v["value"][2]
            vault_fee = v["value"][3]
            vault_liability_shares = v["value"][4]

            leaf = f"0x{merkle_tree.leaf(v["value"]).hex()}"
            proof = []
            for elem in merkle_tree.get_proof(v["treeIndex"]):
                proof.append(f"0x{elem.hex()}")

            result[vault_address] = VaultProof(
                id=vaults[vault_address].vault_ind,
                totalValueWei=vault_total_value_wei,
                inOutDelta=vault_in_out_delta,
                fee=vault_fee,
                liabilityShares=vault_liability_shares,
                leaf=leaf,
                proof=proof,
            )

        return result

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

        cid = self.ipfs_client.publish(dumped_proofs.encode('utf-8'), 'proofs.json')

        return cid

    def publish_tree(
        self, tree: StandardMerkleTree, bs: BlockStamp, proofs_cid: CID, prev_tree_cid: str, chain_config: ChainConfig
    ) -> CID:
        def encoder(o):
            if isinstance(o, bytes):
                return f"0x{o.hex()}"
            if isinstance(o, CID):
                return str(o)
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        output = {
            **dict(tree.dump()),
            "merkleTreeRoot": f"0x{tree.root.hex()}",
            "refSlot": bs.slot_number,
            "blockNumber": bs.block_number,
            "timestamp": chain_config.genesis_time + bs.slot_number * chain_config.seconds_per_slot,
            "proofsCID": str(proofs_cid),
            "prevTreeCID": prev_tree_cid,
            "leafIndexToData": {
                "0": "vault_address",
                "1": "total_value_wei",
                "2": "in_out_delta",
                "3": "fee",
                "4": "liability_shares",
            },
        }

        dumped_tree_str = json.dumps(output, default=encoder)

        cid = self.ipfs_client.publish(dumped_tree_str.encode('utf-8'), 'merkle_tree.json')

        return cid

    def get_current_report_cid(self, bs: BlockStamp) -> LatestReportData:
        return self.vault_hub.get_report(block_identifier=bs.block_number)
