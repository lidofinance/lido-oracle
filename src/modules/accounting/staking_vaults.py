import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import List, Any, Dict, Optional

from eth_typing import ChecksumAddress
from oz_merkle_tree import StandardMerkleTree
from web3 import Web3
from web3.module import Module

from src.modules.accounting.types import VaultsMap, VaultTreeNode, \
    MerkleTreeData, MerkleValue, VaultInfoRaw
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import Validator, PendingDeposit
from src.providers.execution.contracts.lazy_oracle import LazyOracleContract
from src.providers.execution.contracts.lido import LidoContract
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
    lido: LidoContract
    vault_hub: VaultHubContract
    lazy_oracle: LazyOracleContract

    def __init__(self, w3: Web3, cl: ConsensusClient, ipfs: MultiIPFSProvider, lido: LidoContract, vault_hub: VaultHubContract, lazy_oracle: LazyOracleContract) -> None:
        super().__init__(w3)

        self.w3 = w3
        self.ipfs_client = ipfs
        self.cl = cl
        self.lido = lido
        self.vault_hub = vault_hub
        self.lazy_oracle = lazy_oracle

    def get_vaults(self, block_number: int) -> VaultsMap:
        vaults = self.lazy_oracle.get_all_vaults(block_identifier=block_number)
        if len(vaults) == 0:
            return {}

        out = VaultsMap()
        for vault in vaults:
            out[vault.vault] = vault

        return out

    def get_vaults_total_values(self
            , blockstamp: BlockStamp
            , validators: list[Validator]
            , pending_deposits: list[PendingDeposit]
    ) -> list[int]:
        vaults = self.get_vaults(blockstamp.block_number)
        if len(vaults) == 0:
            return []

        vaults_validators = StakingVaults._connect_vaults_to_validators(validators, vaults)
        vaults_pending_deposits = StakingVaults._connect_vaults_to_pending_deposits(pending_deposits, vaults)

        vaults_total_values = [0] * len(vaults)

        for vault_address, vault in vaults.items():
            vaults_total_values[vault.vault_ind] = vault.balance
            vault_validators = vaults_validators.get(vault_address, [])
            vault_pending_deposits = vaults_pending_deposits.get(vault_address, [])

            # Add active validators balances
            if vault_address in vaults_validators:
                vaults_total_values[vault.vault_ind] += self._calculate_vault_validators_balances(vault_validators)

            # Add pending deposits balances
            if vault_address in vaults_pending_deposits:
                vaults_total_values[vault.vault_ind] += self._calculate_pending_deposits_balances(
                    validators,
                    pending_deposits,
                    vault_validators,
                    vault_pending_deposits,
                    vault.withdrawal_credentials,
                )

            logger.info(
                {
                    'msg': f'Vault values for vault: {vault_address}.',
                    'vault_in_out_delta': vault.in_out_delta,
                    'vault_value': vaults_total_values[vault.vault_ind],
                }
            )

        return vaults_total_values

    def publish_proofs(self, tree: StandardMerkleTree, bs: BlockStamp, vaults: VaultsMap) -> CID:
        data = self._get_vault_to_proof_map(tree, vaults)

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
            self, tree: StandardMerkleTree, bs: BlockStamp, proofs_cid: CID, prev_tree_cid: str,
            chain_config: ChainConfig
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

    def get_prev_report(self, bs: BlockStamp) -> Optional[MerkleTreeData]:
        report = self.lazy_oracle.get_report(block_identifier=bs.block_number)
        if report is None:
            return None
        return self.get_vault_report(report.cid)

    def get_prev_cid(self, bs: BlockStamp) -> str:
        report = self.lazy_oracle.get_report(block_identifier=bs.block_number)
        if report is None:
            return ""
        return report.cid

    @staticmethod
    def get_vault_prev_fees(report_data: MerkleTreeData) -> dict[str, int]:
        prev_vault_fees = {}
        for merkle_value in report_data.values:
            prev_vault_fees[merkle_value.vault_address] = merkle_value.fee

        return prev_vault_fees

    def _calculate_pending_deposits_balances(
            self,
            validators: list[Validator],
            pending_deposits: list[PendingDeposit],
            vault_validators: list[Validator],
            vault_pending_deposits: list[PendingDeposit],
            vault_withdrawal_credentials: str,
    ) -> int:
        validator_pubkeys = set(validator.validator.pubkey for validator in validators)
        vault_validator_pubkeys = set(validator.validator.pubkey for validator in vault_validators)
        deposits_by_pubkey: dict[str, list[PendingDeposit]] = defaultdict(list)

        for deposit in vault_pending_deposits:
            deposits_by_pubkey[deposit.pubkey].append(deposit)

        total_value = 0

        for pubkey, deposits in deposits_by_pubkey.items():
            deposit_value = sum(Web3.to_wei(int(deposit.amount), 'gwei') for deposit in deposits)

            # Case 1: Validator exists and is already bound to this vault
            if pubkey in vault_validator_pubkeys:
                total_value += deposit_value
                continue

            # Case 2: Validator exists but not bound to this vault
            if pubkey in validator_pubkeys:
                validator = next(v for v in validators if v.validator.pubkey == pubkey)
                if validator.validator.withdrawal_credentials == vault_withdrawal_credentials:
                    total_value += deposit_value
                else:
                    logger.warning(
                        {
                            'msg': f'Skipping pending deposits for key {pubkey} because validator is not bound to the vault',
                            'validator': validator,
                        }
                    )
                continue

            # Case 3: No validator found for this pubkey - validate deposits
            deposits_for_pubkey = [d for d in pending_deposits if d.pubkey == pubkey]
            valid_deposits = self._filter_valid_deposits(vault_withdrawal_credentials, deposits_for_pubkey)

            if valid_deposits:
                valid_value = sum(Web3.to_wei(int(d.amount), 'gwei') for d in valid_deposits)
                total_value += valid_value

        return total_value

    @staticmethod
    def build_tree_data(vaults: VaultsMap, vaults_values: list[int], vaults_fees: list[int]) -> list[VaultTreeNode]:
        """Build tree data structure from vaults and their values."""
        tree_data: list[VaultTreeNode] = [('', 0, 0, 0, 0) for _ in range(len(vaults))]

        for vault_address, vault in vaults.items():
            vault_fee = 0
            if 0 <= vault.vault_ind < len(vaults_fees):
                vault_fee = vaults_fees[vault.vault_ind]

            tree_data[vault.vault_ind] = (
                vault_address,
                vaults_values[vault.vault_ind],
                vault.in_out_delta,
                vault_fee,
                vault.liability_shares,
            )

        return tree_data

    @staticmethod
    def _filter_valid_deposits(
            vault_withdrawal_credentials: str,
            deposits: list[PendingDeposit]
    ) -> list[PendingDeposit]:
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

            if deposit.withdrawal_credentials != vault_withdrawal_credentials:
                logger.warning(
                    {
                        'msg': f'Invalid withdrawal credentials for proven deposit: {deposit}. Skipping any further pending deposits count.',
                    }
                )
                # In case the first deposit is a VALID, but WC are NOT matching the vault's WC,
                # we should return an empty deposit list because it means that all the future deposits
                # will be mapped to the wrong WC and will not be under the vault's control
                return []

            # Mark that we found a valid deposit and include it
            valid_found = True
            valid_deposits.append(deposit)

        return valid_deposits

    @staticmethod
    def get_merkle_tree(data: list[VaultTreeNode]) -> StandardMerkleTree:
        return StandardMerkleTree(data, ("address", "uint256", "uint256", "uint256", "uint256"))

    @staticmethod
    def _get_vault_to_proof_map(merkle_tree: StandardMerkleTree, vaults: VaultsMap) -> dict[str, VaultProof]:
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

    @staticmethod
    def _calculate_vault_validators_balances(validators: list[Validator]) -> int:
        return sum(Web3.to_wei(int(validator.balance), 'gwei') for validator in validators)

    @staticmethod
    def _connect_vaults_to_validators(validators: list[Validator], vault_addresses: VaultsMap) -> VaultToValidators:
        wc_vault_map: dict[str, VaultInfoRaw] = {
            vault_data.withdrawal_credentials: vault_data for vault_data in vault_addresses.values()
        }

        result: VaultToValidators = defaultdict(list)
        for validator in validators:
            wc = validator.validator.withdrawal_credentials

            if wc in wc_vault_map:
                vault = wc_vault_map[validator.validator.withdrawal_credentials]
                result[vault.vault].append(validator)

        return result

    @staticmethod
    def _connect_vaults_to_pending_deposits(
            pending_deposits: list[PendingDeposit], vault_addresses: VaultsMap
    ) -> VaultToPendingDeposits:
        wc_vault_map: dict[str, VaultInfoRaw] = {
            vault_data.withdrawal_credentials: vault_data for vault_data in vault_addresses.values()
        }

        result: VaultToPendingDeposits = defaultdict(list)
        for deposit in pending_deposits:
            wc = deposit.withdrawal_credentials

            if wc in wc_vault_map:
                vault = wc_vault_map[deposit.withdrawal_credentials]
                result[vault.vault].append(deposit)

        return result

    def get_vault_report(self, tree_cid: str) -> MerkleTreeData:
        bb = self.ipfs_client.fetch(CID(tree_cid))
        return self.parse_merkle_tree_data(bb)

    @staticmethod
    def parse_merkle_tree_data(raw_bytes: bytes) -> MerkleTreeData:
        data = json.loads(raw_bytes.decode("utf-8"))

        index_map: Dict[str, str] = data["leafIndexToData"]

        def decode_value(entry: Dict[str, Any]) -> MerkleValue:
            value_list = entry["value"]
            value_dict = {index_map[str(i)]: v for i, v in enumerate(value_list)}
            return MerkleValue(**value_dict)

        decoded_values = [decode_value(entry) for entry in data["values"]]
        tree_indices = [entry["treeIndex"] for entry in data["values"]]

        return MerkleTreeData(
            format=data["format"],
            leaf_encoding=data["leafEncoding"],
            tree=data["tree"],
            values=decoded_values,
            tree_indices=tree_indices,
            merkle_tree_root=data["merkleTreeRoot"],
            ref_slot=data["refSlot"],
            block_number=data["blockNumber"],
            timestamp=data["timestamp"],
            proofs_cid=data["proofsCID"],
            prev_tree_cid=data["prevTreeCID"]
        )
