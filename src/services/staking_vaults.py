import json
import logging
from collections import defaultdict
from dataclasses import asdict
from decimal import ROUND_UP, Decimal
from typing import Any, Optional

from eth_typing import BlockNumber, HexStr
from oz_merkle_tree import StandardMerkleTree
from web3.types import BlockIdentifier, Wei

from src.constants import TOTAL_BASIS_POINTS
from src.modules.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultEventType,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
    VaultConnectedEvent,
)
from src.modules.accounting.types import (
    BLOCKS_PER_YEAR,
    ExtraValue,
    MerkleValue,
    OnChainIpfsVaultReportData,
    Shares,
    StakingVaultIpfsReport,
    VaultFee,
    VaultFeeMap,
    VaultInfo,
    VaultReserveMap,
    VaultsMap,
    VaultToPendingDeposits,
    VaultTotalValueMap,
    VaultToValidators,
    VaultTreeNode,
)
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.consensus.types import PendingDeposit, Validator
from src.providers.ipfs import CID
from src.types import BlockHash, ReferenceBlockStamp, SlotNumber
from src.utils.apr import get_steth_by_shares
from src.utils.deposit_signature import is_valid_deposit_signature
from src.utils.slot import get_blockstamp
from src.utils.types import hex_str_to_bytes
from src.utils.units import gwei_to_wei
from src.utils.validator_state import calculate_vault_validators_balances
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class StakingVaultsService:
    w3: Web3

    def __init__(self, w3: Web3) -> None:
        self.w3 = w3

    def get_vaults(self, block_identifier: BlockHash | BlockNumber) -> VaultsMap:
        vaults = self.w3.lido_contracts.lazy_oracle.get_all_vaults(block_identifier=block_identifier)
        return VaultsMap({v.vault: v for v in vaults})

    def get_vaults_total_values(
        self, vaults: VaultsMap, validators: list[Validator], pending_deposits: list[PendingDeposit], genesis_fork_version: str
    ) -> VaultTotalValueMap:
        vaults_validators = StakingVaultsService.get_validators_by_vaults(validators, vaults)
        vaults_pending_deposits = StakingVaultsService.get_pending_deposits_by_vaults(pending_deposits, vaults)
        validator_pubkeys = set(validator.validator.pubkey for validator in validators)

        out: VaultTotalValueMap = {}
        for vault_address, vault in vaults.items():
            out[vault_address] = vault.balance
            vault_validators = vaults_validators[vault_address]
            vault_pending_deposits = vaults_pending_deposits.get(vault_address, [])

            if vault_address in vaults_validators:
                out[vault_address] += calculate_vault_validators_balances(vault_validators)

            # Add pending deposits balances
            if vault_address in vaults_pending_deposits:
                out[vault_address] += self._calculate_pending_deposits_balances(
                    validator_pubkeys=validator_pubkeys,
                    pending_deposits=pending_deposits,
                    vault_validators=vault_validators,
                    vault_pending_deposits=vault_pending_deposits,
                    vault_withdrawal_credentials=vault.withdrawal_credentials,
                    genesis_fork_version=genesis_fork_version
                )

            logger.info(
                {
                    'msg': f'Calculate vault TVL: {vault_address}.',
                    'value': out[vault_address],
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
        vaults_validators = StakingVaultsService.get_validators_by_vaults(validators, vaults)
        slashing_reserve_we_left_shift = self.w3.lido_contracts.oracle_daemon_config.slashing_reserve_we_left_shift(bs.block_hash)
        slashing_reserve_we_right_shift = self.w3.lido_contracts.oracle_daemon_config.slashing_reserve_we_right_shift(bs.block_hash)


        def calc_reserve(balance: Wei, reserve_ratio_bp: int) -> int:
            out = Decimal(balance) * Decimal(reserve_ratio_bp) / Decimal(TOTAL_BASIS_POINTS)
            return int(out.to_integral_value(ROUND_UP))

        vaults_reserves: VaultReserveMap = defaultdict(int)
        for vault_address, vault_validators in vaults_validators.items():
            for validator in vault_validators:
                if validator.validator.slashed:
                    withdrawable_epoch = validator.validator.withdrawable_epoch

                    if withdrawable_epoch - slashing_reserve_we_left_shift <= bs.ref_epoch <= withdrawable_epoch + slashing_reserve_we_right_shift:
                        slot_id = (withdrawable_epoch - slashing_reserve_we_left_shift) * chain_config.slots_per_epoch
                        validator_past_state = self.w3.cc.get_validator_state(SlotNumber(slot_id), validator.index)

                        vaults_reserves[vault_address] += calc_reserve(
                            gwei_to_wei(validator_past_state.balance),
                            vaults[vault_address].reserve_ratio_bp,
                        )

                    elif bs.ref_epoch < withdrawable_epoch - slashing_reserve_we_left_shift:
                        vaults_reserves[vault_address] += calc_reserve(
                            gwei_to_wei(validator.balance), vaults[vault_address].reserve_ratio_bp
                        )

        return vaults_reserves

    @staticmethod
    def tree_encoder(o):
        if isinstance(o, bytes):
            return f"0x{o.hex()}"
        if isinstance(o, CID):
            return str(o)
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")

    def publish_tree(
        self,
        tree: StandardMerkleTree,
        vaults: VaultsMap,
        bs: ReferenceBlockStamp,
        prev_tree_cid: str,
        chain_config: ChainConfig,
        vaults_fee_map: VaultFeeMap,
    ) -> CID:
        output = self.get_dumped_tree(
            tree=tree,
            vaults=vaults,
            bs=bs,
            prev_tree_cid=prev_tree_cid,
            chain_config=chain_config,
            vaults_fee_map=vaults_fee_map,
        )

        dumped_tree_str = json.dumps(output, default=self.tree_encoder)

        return self.w3.ipfs.publish(dumped_tree_str.encode('utf-8'), 'merkle_tree.json')

    @staticmethod
    def get_dumped_tree(
            tree: StandardMerkleTree,
            vaults: VaultsMap,
            bs: ReferenceBlockStamp,
            prev_tree_cid: str,
            chain_config: ChainConfig,
            vaults_fee_map: VaultFeeMap
    ) -> dict[str, Any]:
        def stringify_values(data) -> list[dict[str, str | int]]:
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
            extra_values[vault_adr] = ExtraValue(
                in_out_delta=str(vault_info.in_out_delta),
                prev_fee=str(vaults_fee_map[vault_adr].prev_fee),
                infra_fee=str(vaults_fee_map[vault_adr].infra_fee),
                liquidity_fee=str(vaults_fee_map[vault_adr].liquidity_fee),
                reservation_fee=str(vaults_fee_map[vault_adr].reservation_fee)
            ).to_camel_dict()

        output: dict[str, Any] = {
            **dict(tree.dump()),
            "refSlot": bs.ref_slot,
            "blockHash": bs.block_hash,
            "blockNumber": bs.block_number,
            "timestamp": chain_config.genesis_time + bs.slot_number * chain_config.seconds_per_slot,
            "extraValues": extra_values,
            "prevTreeCID": prev_tree_cid,
            "leafIndexToData": {k.value: v.value for k, v in MerkleValue.leaf_index_to_data().items()},
        }
        output.update(values=values)

        return output

    def get_ipfs_report(self, ipfs_report_cid: str) -> StakingVaultIpfsReport:
        if ipfs_report_cid == "":
            raise ValueError("Arg ipfs_report_cid could not be ''")
        return self.get_vault_report(ipfs_report_cid)

    def get_vault_report(self, tree_cid: str) -> StakingVaultIpfsReport:
        bb = self.w3.ipfs.fetch(CID(tree_cid))
        return StakingVaultIpfsReport.parse_merkle_tree_data(bb)

    def get_latest_onchain_ipfs_report_data(self, block_identifier: BlockIdentifier) -> OnChainIpfsVaultReportData:
        return self.w3.lido_contracts.lazy_oracle.get_latest_report_data(block_identifier)

    def _calculate_pending_deposits_balances(
        self,
        validator_pubkeys: set[str],
        pending_deposits: list[PendingDeposit],
        vault_validators: list[Validator],
        vault_pending_deposits: list[PendingDeposit],
        vault_withdrawal_credentials: str,
        genesis_fork_version: str,
    ) -> int:
        vault_validator_pubkeys = set(validator.validator.pubkey for validator in vault_validators)
        vault_deposits_by_pubkey: dict[str, list[PendingDeposit]] = defaultdict(list)

        for deposit in vault_pending_deposits:
            vault_deposits_by_pubkey[deposit.pubkey].append(deposit)

        total_value = 0

        for pubkey, deposits in vault_deposits_by_pubkey.items():
            # Case 1: Validator exists and is already bound to this vault, count all deposits for this pubkey
            if pubkey in vault_validator_pubkeys:
                total_value += sum(gwei_to_wei(deposit.amount) for deposit in deposits)
                continue

            # Case 2: Validator exists but not bound to this vault, thus we should not count deposits for this pubkey
            if pubkey in validator_pubkeys:
                continue

            # Case 3: No validator found for this pubkey - validate deposits
            deposits_by_pubkey = [d for d in pending_deposits if d.pubkey == pubkey]
            total_value += self._get_valid_deposits_value(vault_withdrawal_credentials, deposits_by_pubkey, genesis_fork_version)

        return total_value

    @staticmethod
    def build_tree_data(
        vaults: VaultsMap,
        vaults_total_values: VaultTotalValueMap,
        vaults_fees: VaultFeeMap,
        vaults_slashing_reserve: VaultReserveMap,
    ) -> list[VaultTreeNode]:
        """Build tree data structure from vaults and their values."""

        tree_data: list[VaultTreeNode] = []
        for vault_address, vault in vaults.items():
            if vault_address not in vaults_total_values:
                raise ValueError(f'Vault {vault_address} is not in total_values')

            if vault_address not in vaults_fees:
                raise ValueError(f'Vault {vault_address} is not in vaults_fees')

            tree_data.append(
                (
                    vault_address,
                    Wei(vaults_total_values[vault_address]),
                    vaults_fees[vault_address].total(),
                    vault.liability_shares,
                    vaults_slashing_reserve.get(vault_address, 0),
                )
            )

        return tree_data

    @staticmethod
    def _get_valid_deposits_value(
        vault_withdrawal_credentials: str, pubkey_deposits: list[PendingDeposit], genesis_fork_version: str
    ) -> int:
        """
        Validates deposit signatures and returns a list of valid deposits.
        Once a valid pending deposit is found, all subsequent deposits are considered valid.
        """
        valid_deposits_value = 0
        valid_found = False

        for deposit in pubkey_deposits:
            # If we've already found a valid pending deposit, accept all subsequent ones
            if valid_found:
                valid_deposits_value += gwei_to_wei(deposit.amount)
                continue

            # Verify the deposit signature
            is_valid = is_valid_deposit_signature(
                pubkey=hex_str_to_bytes(deposit.pubkey),
                withdrawal_credentials=hex_str_to_bytes(deposit.withdrawal_credentials),
                amount_gwei=deposit.amount,
                signature=hex_str_to_bytes(deposit.signature),
                fork_version=genesis_fork_version,
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
                        "msg": (
                            "Missmatch deposit withdrawal_credentials "
                            f"{deposit.withdrawal_credentials} "
                            "to vault withdrawal_credentials "
                            f"{vault_withdrawal_credentials}. "
                            "Skipping any further pending deposits count."
                        )
                    }
                )
                # In case the first deposit is a VALID, but WC are NOT matching the vault's WC,
                # we should return an empty deposit list because it means that all the future deposits
                # will be mapped to the wrong WC and will not be under the vault's control
                return 0

            # Mark that we found a valid deposit and include it
            valid_found = True
            valid_deposits_value += gwei_to_wei(deposit.amount)

        return valid_deposits_value

    @staticmethod
    def get_merkle_tree(data: list[VaultTreeNode]) -> StandardMerkleTree:
        return StandardMerkleTree(data, ("address", "uint256", "uint256", "uint256", "int256"))

    @staticmethod
    def get_validators_by_vaults(validators: list[Validator], vaults: VaultsMap) -> VaultToValidators:
        wc_vault_map: dict[str, VaultInfo] = {
            vault_data.withdrawal_credentials: vault_data for vault_data in vaults.values()
        }

        result: VaultToValidators = defaultdict(list)
        for validator in validators:
            wc = validator.validator.withdrawal_credentials

            if vault := wc_vault_map.get(wc):
                result[vault.vault].append(validator)

        return result

    @staticmethod
    def get_pending_deposits_by_vaults(
        pending_deposits: list[PendingDeposit],
        vaults: VaultsMap
    ) -> VaultToPendingDeposits:
        wc_vault_map: dict[str, VaultInfo] = {
            vault_data.withdrawal_credentials: vault_data for vault_data in vaults.values()
        }

        result: VaultToPendingDeposits = defaultdict(list)
        for deposit in pending_deposits:
            wc = deposit.withdrawal_credentials

            if vault := wc_vault_map.get(wc):
                result[vault.vault].append(deposit)

        return result

    def is_tree_root_valid(self, expected_tree_root: str, merkle_tree: StakingVaultIpfsReport) -> bool:
        tree_data = []
        for vault in merkle_tree.values:
            tree_data.append(
                (
                    vault.vault_address,
                    vault.total_value_wei,
                    vault.fee,
                    vault.liability_shares,
                    vault.slashing_reserve
                )
            )

        rebuild_merkle_tree = self.get_merkle_tree(tree_data)
        root_hex = f'0x{rebuild_merkle_tree.root.hex()}'
        return merkle_tree.tree[0] == root_hex and root_hex == expected_tree_root

    @staticmethod
    def calc_fee_value(value: Decimal, block_elapsed: int, core_apr_ratio: Decimal, fee_bp: int) -> Decimal:
        return value * Decimal(block_elapsed) * core_apr_ratio * Decimal(fee_bp) / Decimal(BLOCKS_PER_YEAR * TOTAL_BASIS_POINTS)

    @staticmethod
    # pylint: disable=too-many-branches
    def calc_liquidity_fee(
        vault_address: str,
        liability_shares: Shares,
        liquidity_fee_bp: int,
        events: defaultdict[str, list[VaultEventType]],
        prev_block_number: BlockNumber,
        current_block: BlockNumber,
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
                │          (shares were higher before burn)
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
            vault_liquidity_fee += StakingVaultsService.calc_fee_value(
                minted_steth, blocks_elapsed, core_apr_ratio, liquidity_fee
            )
        elif len(events[vault_address]) > 0:
            # In case of events, we iterate through them backwards, calculating liquidity fee for each interval based
            # on the `liability_shares` and the elapsed blocks between events.
            events[vault_address].sort(key=lambda x: x.block_number, reverse=True)

            for event in events[vault_address]:
                blocks_elapsed_between_events = current_block - event.block_number
                minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
                vault_liquidity_fee += StakingVaultsService.calc_fee_value(
                    minted_steth_on_event, blocks_elapsed_between_events, core_apr_ratio, liquidity_fee
                )

                if isinstance(event, VaultConnectedEvent):
                    # If we catch a VaultConnectedEvent, it means that in the past there could be no more events,
                    # because the vault was previously disconnected.
                    # Technically, we could skip this check, but it explicitly communicates the business logic and intention.
                    if liability_shares != 0:
                        raise ValueError(
                            f"Wrong vault liquidity shares by vault {vault_address}. Vault had reconnected event and then his vault_liquidity_shares must be 0. got {liability_shares}"
                        )

                    return vault_liquidity_fee, liability_shares

                # Because we are iterating backward in time, events must be applied in reverse.
                # E.g., a burn reduces shares in the future, so going backward we add them back.
                if isinstance(event, VaultFeesUpdatedEvent):
                    liquidity_fee = event.pre_liquidity_fee_bp
                elif isinstance(event, MintedSharesOnVaultEvent):
                    liability_shares -= event.amount_of_shares
                elif isinstance(event, BurnedSharesOnVaultEvent):
                    liability_shares += event.amount_of_shares
                elif isinstance(event, VaultRebalancedEvent):
                    liability_shares += event.shares_burned
                elif isinstance(event, BadDebtWrittenOffToBeInternalizedEvent):
                    liability_shares += event.bad_debt_shares
                elif isinstance(event, BadDebtSocializedEvent):
                    if vault_address == event.vault_donor:
                        liability_shares += event.bad_debt_shares
                    else:
                        liability_shares -= event.bad_debt_shares

                current_block = event.block_number

            blocks_elapsed_between_events = current_block - prev_block_number
            minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
            vault_liquidity_fee += StakingVaultsService.calc_fee_value(
                minted_steth_on_event, blocks_elapsed_between_events, core_apr_ratio, liquidity_fee
            )

        return vault_liquidity_fee, liability_shares

    def _get_start_point_for_fee_calculations(
        self,
        blockstamp: ReferenceBlockStamp,
        latest_onchain_ipfs_report_data: OnChainIpfsVaultReportData,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
    ) -> tuple[Optional[StakingVaultIpfsReport], BlockNumber, HexStr]:
        slots_per_frame = frame_config.epochs_per_frame * chain_config.slots_per_epoch

        if latest_onchain_ipfs_report_data.report_cid != "":
            prev_ipfs_report = self.get_ipfs_report(latest_onchain_ipfs_report_data.report_cid)
            tree_root_hex = Web3.to_hex(latest_onchain_ipfs_report_data.tree_root)

            if not self.is_tree_root_valid(tree_root_hex, prev_ipfs_report):
                raise ValueError(
                    f"Invalid tree root in IPFS report data. "
                    f"Expected: {tree_root_hex}, actual: {prev_ipfs_report.tree[0]}"
            )

            last_processing_ref_slot = self.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)

            ref_block = get_blockstamp(
                self.w3.cc,
                last_processing_ref_slot,
                SlotNumber(int(last_processing_ref_slot) + slots_per_frame)
            )
            return prev_ipfs_report, ref_block.block_number, ref_block.block_hash

        ## When we do NOT HAVE prev IPFS report => we have to check two branches: for mainnet and devnet (genesis vaults support)
        ## Mainnet
        ##   in case when we don't have prev ipfs report - we DO have previous oracle report
        ##   it means we have to take this point for getting fees at the FIRST time only
        last_processing_ref_slot = self.w3.lido_contracts.accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        if last_processing_ref_slot:
            ref_block = get_blockstamp(
                self.w3.cc, last_processing_ref_slot, SlotNumber(int(last_processing_ref_slot) + slots_per_frame)
            )
            return None, ref_block.block_number, ref_block.block_hash

        ## Fresh devnet
        ## We DO not have prev IPFS report, and we DO not have prev Oracle report then we take
        # If skipped, we reference the block from the first non-missed slot (frame length offset presumes availability).
        initial_ref_slot = frame_config.initial_epoch * chain_config.slots_per_epoch
        bs = get_blockstamp(
            self.w3.cc, SlotNumber(initial_ref_slot), SlotNumber(int(initial_ref_slot + slots_per_frame))
        )
        return None, bs.block_number, bs.block_hash

    # This function is complex by design (business logic-heavy),
    # so we disable the pylint warning for too many branches.
    # pylint: disable=too-many-branches
    def get_vaults_fees(
        self,
        blockstamp: ReferenceBlockStamp,
        vaults: VaultsMap,
        vaults_total_values: VaultTotalValueMap,
        latest_onchain_ipfs_report_data: OnChainIpfsVaultReportData,
        core_apr_ratio: Decimal,
        pre_total_pooled_ether: int,
        pre_total_shares: int,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
    ) -> VaultFeeMap:
        prev_ipfs_report, prev_block_number, prev_block_hash = self._get_start_point_for_fee_calculations(
            blockstamp, latest_onchain_ipfs_report_data, frame_config, chain_config
        )
        vaults_on_prev_report = self.get_vaults(BlockHash(HexStr(prev_block_hash)))

        prev_fee = defaultdict(int)
        if prev_ipfs_report is not None:
            for vault in prev_ipfs_report.values:
                prev_fee[vault.vault_address] = vault.fee

        events: defaultdict[str, list[VaultEventType]] = defaultdict(list)
        fees_updated_events = self.w3.lido_contracts.vault_hub.get_vault_fee_updated_events(prev_block_number, blockstamp.block_number)
        minted_events = self.w3.lido_contracts.vault_hub.get_minted_events(prev_block_number, blockstamp.block_number)
        burn_events = self.w3.lido_contracts.vault_hub.get_burned_events(prev_block_number, blockstamp.block_number)
        rebalanced_events = self.w3.lido_contracts.vault_hub.get_vault_rebalanced_events(prev_block_number, blockstamp.block_number)
        bad_debt_socialized_events = self.w3.lido_contracts.vault_hub.get_bad_debt_socialized_events(prev_block_number, blockstamp.block_number)
        written_off_to_be_internalized_events = self.w3.lido_contracts.vault_hub.get_bad_debt_written_off_to_be_internalized_events(prev_block_number, blockstamp.block_number)
        vault_connected_events = self.w3.lido_contracts.vault_hub.get_vault_connected_events(prev_block_number, blockstamp.block_number)

        for fees_updated_event in fees_updated_events:
            events[fees_updated_event.vault].append(fees_updated_event)

        for minted_event in minted_events:
            events[minted_event.vault].append(minted_event)

        for burned_event in burn_events:
            events[burned_event.vault].append(burned_event)

        for rebalanced_event in rebalanced_events:
            events[rebalanced_event.vault].append(rebalanced_event)

        for written_off_event in written_off_to_be_internalized_events:
            events[written_off_event.vault].append(written_off_event)

        for socialized_event in bad_debt_socialized_events:
            events[socialized_event.vault_donor].append(socialized_event)
            events[socialized_event.vault_acceptor].append(socialized_event)

        vault_connected_events_set = set()
        for vault_connected_event in vault_connected_events:
            events[vault_connected_event.vault].append(vault_connected_event)
            vault_connected_events_set.add(vault_connected_event.vault)

        out: VaultFeeMap = {}
        current_block = blockstamp.block_number
        blocks_elapsed = current_block - prev_block_number
        for vault_address, vault_info in vaults.items():
            # Infrastructure fee = Total_value * Lido_Core_APR * Infrastructure_fee_rate
            vaults_total_value = vaults_total_values.get(vault_address, 0)
            vault_infrastructure_fee = StakingVaultsService.calc_fee_value(
                Decimal(vaults_total_value), blocks_elapsed, core_apr_ratio, vault_info.infra_fee_bp
            )

            # Mintable_stETH * Lido_Core_APR * Reservation_liquidity_fee_rate
            vault_reservation_liquidity_fee = StakingVaultsService.calc_fee_value(
                Decimal(vault_info.mintable_st_eth),
                blocks_elapsed,
                core_apr_ratio,
                vault_info.reservation_fee_bp,
            )

            vault_liquidity_fee, liability_shares = StakingVaultsService.calc_liquidity_fee(
                vault_address=vault_address,
                liability_shares=vault_info.liability_shares,
                liquidity_fee_bp=vault_info.liquidity_fee_bp,
                events=events,
                prev_block_number=prev_block_number,
                current_block=blockstamp.block_number,
                pre_total_pooled_ether=Wei(pre_total_pooled_ether),
                pre_total_shares=pre_total_shares,
                core_apr_ratio=core_apr_ratio,
            )

            vault_got_connected_event = vault_address in vault_connected_events_set

            ## If the vault was disconnected and then reconnected between reports,
            ## we must not carry over liability_shares from the previous report.
            ##
            ## The fees were already paid, and the vault essentially starts a new lifecycle from zero.
            if vault_got_connected_event or vault_address not in vaults_on_prev_report:
                prev_liability_shares = 0
            else:
                prev_liability_shares = vaults_on_prev_report[vault_address].liability_shares

            if prev_liability_shares != liability_shares:
                raise ValueError(
                    f"Wrong liability shares by vault {vault_address}. Actual {liability_shares} != Expected {prev_liability_shares}"
                )

            out[vault_address] = VaultFee(
                prev_fee=int(0) if vault_got_connected_event else int(prev_fee[vault_address]),
                infra_fee=int(vault_infrastructure_fee.to_integral_value(ROUND_UP)),
                reservation_fee=int(vault_reservation_liquidity_fee.to_integral_value(ROUND_UP)),
                liquidity_fee=int(vault_liquidity_fee.to_integral_value(ROUND_UP)),
            )

        return out
