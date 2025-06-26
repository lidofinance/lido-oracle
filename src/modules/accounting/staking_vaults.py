import json
import logging
from collections import defaultdict
from dataclasses import asdict
from typing import Any, Dict

from eth_typing import BlockNumber
from oz_merkle_tree import StandardMerkleTree
from web3 import Web3
from web3.module import Module
from web3.types import Wei

from src.constants import SLASHINGS_PENALTY_EPOCHS_WINDOW_LEFT, SLASHINGS_PENALTY_EPOCHS_WINDOW_RIGHT, \
    TOTAL_BASIS_POINTS
from src.modules.accounting.events import VaultFeesUpdatedEvent, BurnedSharesOnVaultEvent, MintedSharesOnVaultEvent
from src.modules.accounting.types import (
    MerkleTreeData,
    MerkleValue,
    VaultInfo,
    VaultProof,
    VaultsMap,
    VaultToPendingDeposits,
    VaultToValidators,
    VaultTreeNode, Shares, BLOCKS_PER_YEAR,
)
from src.modules.submodules.types import ChainConfig
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import PendingDeposit, Validator
from src.providers.execution.contracts.lazy_oracle import LazyOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import CID, MultiIPFSProvider
from src.types import BlockStamp, ReferenceBlockStamp, SlotNumber, BlockHash
from src.utils.apr import get_steth_by_shares
from src.utils.deposit_signature import is_valid_deposit_signature
from src.utils.types import hex_str_to_bytes

logger = logging.getLogger(__name__)

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

    def get_vaults(self, block_identifier: BlockHash | BlockNumber) -> VaultsMap:
        vaults = self.lazy_oracle.get_all_vaults(block_identifier=block_identifier)
        if len(vaults) == 0:
            return {}

        out = VaultsMap()
        for vault in vaults:
            out[vault.vault] = vault

        return out

    def get_vaults_total_values(self
            , vaults: VaultsMap
            , validators: list[Validator]
            , pending_deposits: list[PendingDeposit]
    ) -> list[int]:
        vaults_validators = StakingVaults._connect_vaults_to_validators(validators, vaults)
        vaults_pending_deposits = StakingVaults._connect_vaults_to_pending_deposits(pending_deposits, vaults)

        vaults_total_values = [0] * len(vaults)

        for vault_address, vault in vaults.items():
            vaults_total_values[vault.id()] = vault.balance
            vault_validators = vaults_validators.get(vault_address, [])
            vault_pending_deposits = vaults_pending_deposits.get(vault_address, [])

            # Add active validators balances
            if vault_address in vaults_validators:
                vaults_total_values[vault.id()] += self._calculate_vault_validators_balances(vault_validators)

            # Add pending deposits balances
            if vault_address in vaults_pending_deposits:
                vaults_total_values[vault.id()] += self._calculate_pending_deposits_balances(
                    validators,
                    pending_deposits,
                    vault_validators,
                    vault_pending_deposits,
                    vault.withdrawal_credentials,
                )

            logger.info(
                {
                    'msg': f'Vault values for vault: {vault_address}.',
                    'vault_value': vaults_total_values[vault.id()],
                }
            )

        return vaults_total_values

    def get_vaults_slashing_reserve(self, bs: ReferenceBlockStamp, vaults: VaultsMap, validators: list[Validator], chain_config: ChainConfig) -> list[int]:
        """
            <- Look back 36 days (by spec 18 days)     Look forward 18 days ->
            ┌────────────────────────────┬────────────┬────────────────────────────┐
            │                            │    T=0     │                            │
            │   Slashings accumulator    │   Slash!   │   Future slashes evaluated │
            │       history window       │            │     for penalty window     │
            └────────────────────────────┴────────────┴────────────────────────────┘
                 Penalty applies here ────────────►  Day 18.25
        """
        vaults_validators = StakingVaults._connect_vaults_to_validators(validators, vaults)
        left_margin, right_margin = SLASHINGS_PENALTY_EPOCHS_WINDOW_LEFT, 2 * SLASHINGS_PENALTY_EPOCHS_WINDOW_RIGHT

        vaults_reserves = [0] * len(vaults)
        for vault_address, validator_arr in vaults_validators.items():
            vault_id = vaults[vault_address].id()
            vaults_reserves[vault_id] = Wei(0)

            for validator in validator_arr:
                if validator.validator.slashed:
                    we = validator.validator.withdrawable_epoch

                    if we - left_margin <= bs.ref_epoch <= we + right_margin:
                        slot_id = self._withdrawable_epoch_to_past_slot(we, SLASHINGS_PENALTY_EPOCHS_WINDOW_LEFT, chain_config.slots_per_epoch)
                        validator_state = self.cl.get_validator_state(SlotNumber(slot_id), validator.index)
                        vaults_reserves[vault_id] += Web3.to_wei(int(validator_state.balance), 'gwei') * vaults[
                            vault_address].reserve_ratioBP // TOTAL_BASIS_POINTS

                    elif bs.ref_epoch < we - left_margin:
                        vaults_reserves[vault_id] += Web3.to_wei(int(validator.balance), 'gwei') * vaults[
                            vault_address].reserve_ratioBP // TOTAL_BASIS_POINTS

        return vaults_reserves

    def publish_tree(
            self, tree: StandardMerkleTree, vaults: VaultsMap, bs: ReferenceBlockStamp, prev_tree_cid: str,
            chain_config: ChainConfig
    ) -> CID:
        def encoder(o):
            if isinstance(o, bytes):
                return f"0x{o.hex()}"
            if isinstance(o, CID):
                return str(o)
            if hasattr(o, "__dataclass_fields__"):
                return asdict(o)
            raise TypeError(f"Object of type {type(o)} is not JSON serializable")

        def stringify_values(data) -> list[dict[str, Any]]:
            out = []
            for item in data:
                val = item["value"]
                out.append({
                    "value": (val[0], str(val[1]), str(val[2]), str(val[3]), str(val[4])),
                    "treeIndex": item["treeIndex"],
                })
            return out

        values = stringify_values(tree.values)

        extra_values = {}
        for vault_adr, vault_info in vaults.items():
            extra_values[vault_adr] = {
                "inOutDelta": str(vault_info.in_out_delta)
            }

        output: dict[str, Any] = {
            **dict(tree.dump()),
            "merkleTreeRoot": f"0x{tree.root.hex()}",
            "refSlot": bs.ref_slot,
            "blockHash": bs.block_hash,
            "blockNumber": bs.block_number,
            "timestamp": chain_config.genesis_time + bs.slot_number * chain_config.seconds_per_slot,
            "extraValues": extra_values,
            "prevTreeCID": prev_tree_cid,
            "leafIndexToData": {
                "0": "vaultAddress",
                "1": "totalValueWei",
                "2": "fee",
                "3": "liabilityShares",
                "4": "slashingReserve",
            },
        }
        output.update(values=values)

        dumped_tree_str = json.dumps(output, default=encoder)

        cid = self.ipfs_client.publish(dumped_tree_str.encode('utf-8'), 'merkle_tree.json')

        return cid

    def get_ipfs_report(self, ipfs_report_cid: str) -> MerkleTreeData:
        if ipfs_report_cid == "":
            raise ValueError("Arg ipfs_report_cid could not be ''")
        return self.get_vault_report(ipfs_report_cid)

    def get_prev_cid(self, bs: BlockStamp) -> str:
        report = self.lazy_oracle.get_report(block_identifier=bs.block_hash)
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
    def build_tree_data(vaults: VaultsMap, vaults_values: list[int], vaults_fees: list[int], vaults_slashing_reserve: list[int]) -> list[VaultTreeNode]:
        """Build tree data structure from vaults and their values."""
        tree_data: list[VaultTreeNode] = [('', 0, 0, 0, 0) for _ in range(len(vaults))]

        for vault_address, vault in vaults.items():
            vault_fee = 0
            if 0 <= vault.id() < len(vaults_fees):
                vault_fee = vaults_fees[vault.id()]

            vault_value = 0
            if 0 <= vault.id() < len(vaults_values):
                vault_value = vaults_values[vault.id()]

            vault_slashing_reserve = 0
            if 0 <= vault.id() < len(vaults_slashing_reserve):
                vault_slashing_reserve = vaults_slashing_reserve[vault.id()]

            tree_data[vault.id()] = (
                vault_address,
                vault_value,
                vault_fee,
                vault.liability_shares,
                vault_slashing_reserve
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
        return StandardMerkleTree(data, ("address", "uint256", "uint256", "uint256", "int256"))

    @staticmethod
    def _get_vault_to_proof_map(merkle_tree: StandardMerkleTree, vaults: VaultsMap) -> dict[str, VaultProof]:
        result = {}
        for v in merkle_tree.values:
            vault_address = v["value"][0]
            vault_total_value_wei = v["value"][1]
            vault_fee = v["value"][2]
            vault_liability_shares = v["value"][3]
            vault_slashing_reserve = v["value"][4]

            leaf = f"0x{merkle_tree.leaf(v["value"]).hex()}"
            proof = []
            for elem in merkle_tree.get_proof(v["treeIndex"]):
                proof.append(f"0x{elem.hex()}")

            result[vault_address] = VaultProof(
                id=vaults[vault_address].vault_ind,
                totalValueWei=str(vault_total_value_wei),
                fee=str(vault_fee),
                liabilityShares=str(vault_liability_shares),
                slashingReserve=str(vault_slashing_reserve),
                leaf=leaf,
                proof=proof,
                inOutDelta=str(vaults[vault_address].in_out_delta)
            )

        return result

    @staticmethod
    def _calculate_vault_validators_balances(validators: list[Validator]) -> int:
        return sum(Web3.to_wei(int(validator.balance), 'gwei') for validator in validators)

    @staticmethod
    def _connect_vaults_to_validators(validators: list[Validator], vault_addresses: VaultsMap) -> VaultToValidators:
        wc_vault_map: dict[str, VaultInfo] = {
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
        wc_vault_map: dict[str, VaultInfo] = {
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
            return MerkleValue(
                vault_address=value_dict["vaultAddress"],
                total_value_wei=value_dict["totalValueWei"],
                fee=value_dict["fee"],
                liability_shares=value_dict["liabilityShares"],
                slashing_reserve=value_dict["slashingReserve"],
            )

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
            block_hash=data["blckHash"],
            block_number=data["blockNumber"],
            timestamp=data["timestamp"],
            prev_tree_cid=data["prevTreeCID"],
            extra_values=data["extraValues"],
        )

    @staticmethod
    def _withdrawable_epoch_to_past_slot(withdrawable_epoch: int, epochs_ago: int, slots_per_epoch: int) -> int:
        target_epoch = withdrawable_epoch - epochs_ago
        target_slot = target_epoch * slots_per_epoch
        return target_slot

    @staticmethod
    def calc_fee_value(value: int | float, block_elapsed: int, core_apr_ratio: float, fee_bp: int) -> float:
        return value * block_elapsed * core_apr_ratio * fee_bp / (BLOCKS_PER_YEAR * TOTAL_BASIS_POINTS)

    @staticmethod
    def calc_liquidity_fee(
            vault_address: str, liability_shares: Shares, liquidity_fee_bp: int,
            events: dict, prev_block_number: int, current_block: int,
            pre_total_pooled_ether: Wei,
            pre_total_shares: Shares,
            core_apr_ratio: float,
    ) -> [float, Shares]:
        """
             Liquidity fee = Minted_stETH * Lido_Core_APR * Liquidity_fee_rate
             NB: below we determine liquidity fee for the vault as a bunch of intervals between minting, burning and
                 fee change events.

             In case of no events, we just use `liability_shares` to calculate minted stETH.
        """
        vault_liquidity_fee: float = 0
        liquidity_fee = liquidity_fee_bp

        if vault_address not in events:
            # TODO: DRY with the next block
            blocks_elapsed = current_block - prev_block_number
            minted_steth = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
            vault_liquidity_fee = StakingVaults.calc_fee_value(minted_steth, blocks_elapsed, core_apr_ratio, liquidity_fee)
        elif len(events[vault_address]) > 0:
            # In case of events, we iterate through them backwards, calculating liquidity fee for each interval based
            # on the `liability_shares` and the elapsed blocks between events.
            events[vault_address].sort(key=lambda x: x.block_number, reverse=True)

            for event in events[vault_address]:
                blocks_elapsed_between_events = current_block - event.block_number
                minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether,
                                                                        pre_total_shares)
                vault_liquidity_fee += StakingVaults.calc_fee_value(minted_steth_on_event, blocks_elapsed_between_events,
                                                                 core_apr_ratio, liquidity_fee)

                if isinstance(event, VaultFeesUpdatedEvent):
                    liquidity_fee = event.pre_liquidity_fee_bp
                    current_block = event.block_number
                    continue
                if isinstance(event, BurnedSharesOnVaultEvent):
                    liability_shares += event.amount_of_shares
                    current_block = event.block_number
                    continue
                if isinstance(event, MintedSharesOnVaultEvent):
                    liability_shares -= event.amount_of_shares
                    current_block = event.block_number

            blocks_elapsed_between_events = current_block - prev_block_number
            minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether,
                                                                    pre_total_shares)
            vault_liquidity_fee += StakingVaults.calc_fee_value(minted_steth_on_event, blocks_elapsed_between_events,
                                                       core_apr_ratio, liquidity_fee)

        return vault_liquidity_fee, liability_shares
