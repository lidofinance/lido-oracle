import json
import logging
from collections import defaultdict
from dataclasses import asdict
from typing import Any, Dict, Optional

from eth_typing import BlockNumber, HexStr
from oz_merkle_tree import StandardMerkleTree
from web3 import Web3
from web3.module import Module
from web3.types import Wei

from src.constants import TOTAL_BASIS_POINTS, PRECISION_E27, EPOCHS_PER_SLASHINGS_VECTOR
from src.modules.accounting.events import VaultFeesUpdatedEvent, BurnedSharesOnVaultEvent, MintedSharesOnVaultEvent, \
    VaultRebalancedEvent, BadDebtSocializedEvent, BadDebtWrittenOffToBeInternalizedEvent
from src.modules.accounting.types import (
    MerkleTreeData,
    MerkleValue,
    VaultInfo,
    VaultsMap,
    VaultToPendingDeposits,
    VaultToValidators,
    VaultTreeNode,
    Shares,
    BLOCKS_PER_YEAR,
    VaultTotalValueMap,
    VaultFeeMap,
    VaultReserveMap,
    VaultFee,
)
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.consensus.client import ConsensusClient
from src.providers.consensus.types import PendingDeposit, Validator
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.lazy_oracle import LazyOracleContract
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import CID, MultiIPFSProvider
from src.types import BlockStamp, ReferenceBlockStamp, SlotNumber, BlockHash
from src.utils.apr import get_steth_by_shares
from src.utils.deposit_signature import is_valid_deposit_signature
from src.utils.slot import get_blockstamp
from src.utils.types import hex_str_to_bytes, bytes_to_hex_str
from decimal import Decimal, localcontext, ROUND_UP

logger = logging.getLogger(__name__)


class StakingVaults(Module):
    w3: Web3
    ipfs_client: MultiIPFSProvider
    cl: ConsensusClient
    lido: LidoContract
    vault_hub: VaultHubContract
    lazy_oracle: LazyOracleContract
    accounting_oracle: AccountingOracleContract

    def __init__(
        self,
        w3: Web3,
        cl: ConsensusClient,
        ipfs: MultiIPFSProvider,
        lido: LidoContract,
        vault_hub: VaultHubContract,
        lazy_oracle: LazyOracleContract,
        accounting_oracle: AccountingOracleContract,
    ) -> None:
        super().__init__(w3)

        self.w3 = w3
        self.ipfs_client = ipfs
        self.cl = cl
        self.lido = lido
        self.vault_hub = vault_hub
        self.lazy_oracle = lazy_oracle
        self.accounting_oracle = accounting_oracle

    def get_vaults(self, block_identifier: BlockHash | BlockNumber) -> VaultsMap:
        vaults = self.lazy_oracle.get_all_vaults(block_identifier=block_identifier)
        if len(vaults) == 0:
            return {}

        out = VaultsMap()
        for vault in vaults:
            out[vault.vault] = vault

        return out

    def get_vaults_total_values(
        self, vaults: VaultsMap, validators: list[Validator], pending_deposits: list[PendingDeposit]
    ) -> VaultTotalValueMap:
        vaults_validators = StakingVaults._connect_vaults_to_validators(validators, vaults)
        vaults_pending_deposits = StakingVaults._connect_vaults_to_pending_deposits(pending_deposits, vaults)

        out: VaultTotalValueMap = defaultdict(int)
        for vault_address, vault in vaults.items():
            out[vault_address] = vault.balance
            vault_validators = vaults_validators.get(vault_address, [])
            vault_pending_deposits = vaults_pending_deposits.get(vault_address, [])

            if vault_address in vaults_validators:
                out[vault_address] += self._calculate_vault_validators_balances(vault_validators)

            # Add pending deposits balances
            if vault_address in vaults_pending_deposits:
                out[vault_address] += self._calculate_pending_deposits_balances(
                    pending_deposits,
                    vault_validators,
                    vault_pending_deposits,
                    vault.withdrawal_credentials,
                )

            logger.info(
                {
                    'msg': f'Vault values for vault: {vault_address}.',
                    'vault_value': out[vault_address],
                }
            )

        return out

    def get_vaults_slashing_reserve(
        self, bs: ReferenceBlockStamp, vaults: VaultsMap, validators: list[Validator], chain_config: ChainConfig
    ) -> VaultReserveMap:
        """
        Note1: we = withdrawable_epoch
        Note2: we don't know when the slashing really happened - this why we take distance [-36d, +36d]

        <- Look back 36d(8_192 epochs)             Look forward 36d(8_192 epochs) ->
        ┌────────────────────────────┬────────────┬────────────────────────────┐
        │   Slashings accumulator    │    we!     │   Future slashes evaluated │
        │       history window       │            │     for penalty window     │
        └────────────────────────────┴────────────┴────────────────────────────┘

        1. (we -36d) <= ref_epoch <= (we +36d): use PAST slot for getting validator's balance
        2. ref_epoch < (we -36d): use CURRENT validator's balance (before slashing period)
        3. ref_epoch > (we +36d): skip reserve (after slashing period)
        """
        vaults_validators = StakingVaults._connect_vaults_to_validators(validators, vaults)

        with localcontext() as ctx:
            ctx.prec = PRECISION_E27

            def calc_reserve(balance: Wei, reserve_ratioBP: int) -> int:
                out = Decimal(balance) * Decimal(reserve_ratioBP) / Decimal(TOTAL_BASIS_POINTS)
                return int(out.to_integral_value(ROUND_UP))

            vaults_reserves: VaultReserveMap = defaultdict(int)
            for vault_address, vault_validators in vaults_validators.items():
                for validator in vault_validators:
                    if validator.validator.slashed:
                        withdrawable_epoch = validator.validator.withdrawable_epoch

                        if withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR <= bs.ref_epoch <= withdrawable_epoch + EPOCHS_PER_SLASHINGS_VECTOR:
                            slot_id = (withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR) * chain_config.slots_per_epoch
                            validator_past_state = self.cl.get_validator_state(SlotNumber(slot_id), validator.index)

                            vaults_reserves[vault_address] += calc_reserve(
                                Web3.to_wei(int(validator_past_state.balance), 'gwei'),
                                vaults[vault_address].reserve_ratioBP,
                            )

                        elif bs.ref_epoch < withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR:
                            vaults_reserves[vault_address] += calc_reserve(
                                Web3.to_wei(int(validator.balance), 'gwei'), vaults[vault_address].reserve_ratioBP
                            )

            return vaults_reserves

    def publish_tree(
        self,
        tree: StandardMerkleTree,
        vaults: VaultsMap,
        bs: ReferenceBlockStamp,
        prev_tree_cid: str,
        chain_config: ChainConfig,
        vaults_fee_map: VaultFeeMap
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
                out.append(
                    {
                        "value": (item["value"][0],) + tuple(str(x) for x in item["value"][1:]),
                        "treeIndex": item["treeIndex"],
                    }
                )
            return out

        values = stringify_values(tree.values)

        extra_values = {}
        for vault_adr, vault_info in vaults.items():
            extra_values[vault_adr] = {
                "inOutDelta": str(vault_info.in_out_delta),
                "prevFee":  str(vaults_fee_map[vault_adr].prev_fee),
                "infraFee": str(vaults_fee_map[vault_adr].infra_fee),
                "liquidityFee": str(vaults_fee_map[vault_adr].liquidity_fee),
                "reservationFee": str(vaults_fee_map[vault_adr].reservation_fee),
            }

        output: dict[str, Any] = {
            **dict(tree.dump()),
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

    def _calculate_pending_deposits_balances(
        self,
        pending_deposits: list[PendingDeposit],
        vault_validators: list[Validator],
        vault_pending_deposits: list[PendingDeposit],
        vault_withdrawal_credentials: str,
    ) -> int:
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

            # Case 2: No validator found for this pubkey - validate deposits
            deposits_for_pubkey = [d for d in pending_deposits if d.pubkey == pubkey]
            valid_deposits = self._filter_valid_deposits(vault_withdrawal_credentials, deposits_for_pubkey)

            if valid_deposits:
                valid_value = sum(Web3.to_wei(int(d.amount), 'gwei') for d in valid_deposits)
                total_value += valid_value

        return total_value

    @staticmethod
    def build_tree_data(
        vaults: VaultsMap,
        vaults_values: VaultTotalValueMap,
        vaults_fees: VaultFeeMap,
        vaults_slashing_reserve: VaultReserveMap,
    ) -> list[VaultTreeNode]:
        """Build tree data structure from vaults and their values."""

        tree_data: list[VaultTreeNode] = []
        for vault_address, vault in vaults.items():
            vault_total_fee = 0
            vaults_fee = vaults_fees.get(vault_address)
            if vaults_fee is not None:
                vault_total_fee = vaults_fee.total()

            tree_data.append(
                (
                    vault_address,
                    vaults_values.get(vault_address, 0),
                    vault_total_fee,
                    vault.liability_shares,
                    vaults_slashing_reserve.get(vault_address, 0),
                )
            )

        return tree_data

    @staticmethod
    def _filter_valid_deposits(
        vault_withdrawal_credentials: str, deposits: list[PendingDeposit]
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
                        'msg': f'Invalid deposit signature for deposit: {deposit.signature}.',
                    }
                )
                continue

            if deposit.withdrawal_credentials != vault_withdrawal_credentials:
                logger.warning(
                    {
                        'msg': f'Missmatch deposit withdrawal_credentials {deposit.withdrawal_credentials} to vault withdrawal_credentials {vault_withdrawal_credentials}. Skipping any further pending deposits count.',
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
                total_value_wei=int(value_dict["totalValueWei"]),
                fee=int(value_dict["fee"]),
                liability_shares=int(value_dict["liabilityShares"]),
                slashing_reserve=int(value_dict["slashingReserve"]),
            )

        decoded_values = [decode_value(entry) for entry in data["values"]]
        tree_indices = [entry["treeIndex"] for entry in data["values"]]

        return MerkleTreeData(
            format=data["format"],
            leaf_encoding=data["leafEncoding"],
            tree=data["tree"],
            values=decoded_values,
            tree_indices=tree_indices,
            ref_slot=data["refSlot"],
            block_hash=data["blockHash"],
            block_number=data["blockNumber"],
            timestamp=data["timestamp"],
            prev_tree_cid=data["prevTreeCID"],
            extra_values=data["extraValues"],
        )

    @staticmethod
    def calc_fee_value(value: Decimal, block_elapsed: int, core_apr_ratio: Decimal, fee_bp: int) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = PRECISION_E27
            return value * Decimal(block_elapsed) * core_apr_ratio * Decimal(fee_bp) / Decimal(BLOCKS_PER_YEAR * TOTAL_BASIS_POINTS)

    @staticmethod
    def calc_liquidity_fee(
        vault_address: str,
        liability_shares: Shares,
        liquidity_fee_bp: int,
        events: dict,
        prev_block_number: int,
        current_block: int,
        pre_total_pooled_ether: Wei,
        pre_total_shares: Shares,
        core_apr_ratio: Decimal,
    ) -> tuple[Decimal, Shares]:
        """
        Liquidity fee = Minted_stETH × Lido_Core_APR × Liquidity_fee_rate

        We calculate the liquidity fee for the vault as a series of intervals
        between minting, burning, and fee update events.

        If there are no events, we just use `liability_shares` to compute minted stETH.

        Burn: In the future, shares go down; backwards, they go up.
        Mint: In the future, shares go up; backwards, they go down.

          liability_shares (Y)
                  ↑
                  │
                  │
                  │
                  │             (shares were higher before burn)
                  │                 ┌──────────────
                  │                 │              │
                  │                 │              │
                  ┌─────────────────┘              │
                  │                 │              │  (shares decreased)
                  │                 │              │───────────│
                  │                 │              │           │
                  │                 │              │           │
                  └─────────────────┴──────────────┴───────────┴────────▶ block_number (X)

                                 mintEvent      burnEvent  current_block

                        ◄─────────────────────── processing backwards in time
        """
        vault_liquidity_fee = Decimal(0)
        liquidity_fee = liquidity_fee_bp

        if vault_address not in events:
            blocks_elapsed = current_block - prev_block_number
            minted_steth = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
            vault_liquidity_fee += StakingVaults.calc_fee_value(
                minted_steth, blocks_elapsed, core_apr_ratio, liquidity_fee
            )
        elif len(events[vault_address]) > 0:
            # In case of events, we iterate through them backwards, calculating liquidity fee for each interval based
            # on the `liability_shares` and the elapsed blocks between events.
            events[vault_address].sort(key=lambda x: x.block_number, reverse=True)

            for event in events[vault_address]:
                blocks_elapsed_between_events = current_block - event.block_number
                minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
                vault_liquidity_fee += StakingVaults.calc_fee_value(
                    minted_steth_on_event, blocks_elapsed_between_events, core_apr_ratio, liquidity_fee
                )

                # Because we are iterating backward in time, events must be applied in reverse.
                # E.g., a burn reduces shares in the future, so going backward we add them back.
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

                if isinstance(event, VaultRebalancedEvent):
                    liability_shares += event.shares_burned
                    current_block = event.block_number
                    continue

                if isinstance(event, BadDebtSocializedEvent):
                    if vault_address == event.vault_donor:
                        liability_shares += event.bad_debt_shares
                    else:
                        liability_shares -= event.bad_debt_shares
                    current_block = event.block_number
                    continue

                if isinstance(event, BadDebtWrittenOffToBeInternalizedEvent):
                    liability_shares += event.bad_debt_shares
                    current_block = event.block_number
                    continue

            blocks_elapsed_between_events = current_block - prev_block_number
            minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
            vault_liquidity_fee += StakingVaults.calc_fee_value(
                minted_steth_on_event, blocks_elapsed_between_events, core_apr_ratio, liquidity_fee
            )

        return vault_liquidity_fee, liability_shares

    def _get_start_point_for_fee_calculations(
        self, blockstamp: ReferenceBlockStamp, prev_ipfs_report_cid: str, frame_config: FrameConfig, chain_config: ChainConfig
    ) -> tuple[Optional[MerkleTreeData], int, str]:
        if prev_ipfs_report_cid != "":
            prev_ipfs_report = self.get_ipfs_report(prev_ipfs_report_cid)
            return prev_ipfs_report, prev_ipfs_report.block_number, prev_ipfs_report.block_hash

        slots_per_frame = frame_config.epochs_per_frame * chain_config.slots_per_epoch
        ## When we do NOT HANE prev IPFS report => we have to check two branches: for mainnet and devnet (genesis vaults support)
        ## Mainnet
        ##   in case when we don't have prev ipfs report - we DO have previous oracle report
        ##   it means we have to take this point for getting fees at the FIRST time only
        last_processing_ref_slot = self.accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        if last_processing_ref_slot:
            ref_block = get_blockstamp(
                self.cl, last_processing_ref_slot, SlotNumber(int(last_processing_ref_slot) + slots_per_frame)
            )
            return None, ref_block['number'], bytes_to_hex_str(ref_block['hash'])

        ## Fresh devnet
        ## We DO not have prev IPFS report, and we DO not have prev Oracle report then we take
        # If skipped, we reference the block from the first non-missed slot (frame length offset guarantees availability).
        initial_ref_slot = frame_config.initial_epoch * chain_config.slots_per_epoch
        block = get_blockstamp(self.cl, SlotNumber(initial_ref_slot), SlotNumber(int(initial_ref_slot + slots_per_frame)))
        return None, block['number'], bytes_to_hex_str(block['hash'])

    def get_vaults_fees(
        self,
        blockstamp: ReferenceBlockStamp,
        vaults: VaultsMap,
        vaults_total_values: VaultTotalValueMap,
        prev_ipfs_report_cid: str,
        core_apr_ratio: Decimal,
        pre_total_pooled_ether: int,
        pre_total_shares: int,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
    ) -> VaultFeeMap:
        prev_ipfs_report, prev_block_number, prev_block_hash = self._get_start_point_for_fee_calculations(
            blockstamp, prev_ipfs_report_cid, frame_config, chain_config
        )
        vaults_on_prev_report = self.get_vaults(BlockHash(HexStr(prev_block_hash)))

        prev_fee = defaultdict(int)
        if prev_ipfs_report is not None:
            for vault in prev_ipfs_report.values:
                prev_fee[vault.vault_address] = vault.fee

        events = defaultdict(list)
        fees_updated_events = self.vault_hub.get_vaults_fee_updated_events(prev_block_number, blockstamp.block_number)
        minted_events = self.vault_hub.get_minted_events(prev_block_number, blockstamp.block_number)
        burn_events = self.vault_hub.get_burned_events(prev_block_number, blockstamp.block_number)

        rebalanced_events = self.vault_hub.get_vaults_rebalanced_events(prev_block_number, blockstamp.block_number)
        bad_debt_socialized_events = self.vault_hub.get_vaults_bad_debt_socialized_events(prev_block_number, blockstamp.block_number)
        written_off_to_be_internalized_events = self.vault_hub.get_vaults_bad_debt_written_off_to_be_internalized_events(prev_block_number, blockstamp.block_number)

        for event in fees_updated_events:
            events[event.vault].append(event)

        for event in minted_events:
            events[event.vault].append(event)

        for event in burn_events:
            events[event.vault].append(event)

        for event in rebalanced_events:
            events[event.vault].append(event)

        for event in written_off_to_be_internalized_events:
            events[event.vault].append(event)

        for event in bad_debt_socialized_events:
            events[event.vault_donor].append(event)
            events[event.vault_acceptor].append(event)

        out: VaultFeeMap = {}
        current_block = int(blockstamp.block_number)
        blocks_elapsed = current_block - prev_block_number
        for vault_address, vault_info in vaults.items():
            # Infrastructure fee = Total_value * Lido_Core_APR * Infrastructure_fee_rate
            vaults_total_value = vaults_total_values.get(vault_address, 0)
            vault_infrastructure_fee = StakingVaults.calc_fee_value(
                Decimal(vaults_total_value), blocks_elapsed, core_apr_ratio, vault_info.infra_feeBP
            )

            # Mintable_stETH * Lido_Core_APR * Reservation_liquidity_fee_rate
            vault_reservation_liquidity_fee = StakingVaults.calc_fee_value(
                Decimal(vault_info.mintable_capacity_StETH),
                blocks_elapsed,
                core_apr_ratio,
                vault_info.reservation_feeBP,
            )

            vault_liquidity_fee, liability_shares = StakingVaults.calc_liquidity_fee(
                vault_address,
                vault_info.liability_shares,
                vault_info.liquidity_feeBP,
                events,
                prev_block_number,
                int(blockstamp.block_number),
                Wei(pre_total_pooled_ether),
                pre_total_shares,
                core_apr_ratio,
            )

            prev_liability_shares = 0
            if vaults_on_prev_report.get(vault_address) is not None:
                prev_liability_shares = vaults_on_prev_report.get(vault_address).liability_shares  # type: ignore[union-attr]

            if prev_liability_shares != liability_shares:
                raise ValueError(
                    f"Wrong liability shares by vault {vault_address}. Actual {liability_shares} != Expected {prev_liability_shares}"
                )

            out[vault_address] = VaultFee(
                prev_fee=int(prev_fee[vault_address]),
                infra_fee=int(vault_infrastructure_fee.to_integral_value(ROUND_UP)),
                reservation_fee=int(vault_reservation_liquidity_fee.to_integral_value(ROUND_UP)),
                liquidity_fee=int(vault_liquidity_fee.to_integral_value(ROUND_UP))
            )

        return out
