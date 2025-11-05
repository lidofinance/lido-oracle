import json
import logging
from collections import defaultdict
from dataclasses import asdict
from decimal import ROUND_UP, Decimal
from typing import Any, Optional

from eth_typing import BlockNumber
from oz_merkle_tree import StandardMerkleTree
from web3.types import BlockIdentifier, Wei

from src.constants import (
    MIN_DEPOSIT_AMOUNT,
    TOTAL_BASIS_POINTS,
)
from src.modules.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultConnectedEvent,
    VaultEventType,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
    sort_events,
)
from src.modules.accounting.types import (
    BLOCKS_PER_YEAR,
    ExtraValue,
    MerkleValue,
    OnChainIpfsVaultReportData,
    Shares,
    StakingVaultIpfsReport,
    ValidatorStage,
    ValidatorStatus,
    VaultFee,
    VaultFeeMap,
    VaultInfo,
    VaultReserveMap,
    VaultsMap,
    VaultTotalValueMap,
    VaultToValidators,
    VaultTreeNode,
)
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.consensus.types import PendingDeposit, Validator
from src.providers.ipfs import CID
from src.types import FrameNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.apr import get_steth_by_shares
from src.utils.slot import get_blockstamp
from src.utils.units import gwei_to_wei
from src.utils.validator_state import has_far_future_activation_eligibility_epoch
from src.web3py.types import Web3

logger = logging.getLogger(__name__)

MERKLE_TREE_VAULTS_FILENAME = 'staking_vaults_merkle_tree.json'


class StakingVaultsService:
    w3: Web3

    def __init__(self, w3: Web3) -> None:
        self.w3 = w3

    def get_vaults(self, block_identifier: BlockIdentifier = 'latest') -> VaultsMap:
        vaults = self.w3.lido_contracts.lazy_oracle.get_all_vaults(block_identifier=block_identifier)
        return VaultsMap({v.vault: v for v in vaults})

    def get_vaults_total_values(
        self,
        vaults: VaultsMap,
        validators: list[Validator],
        pending_deposits: list[PendingDeposit],
        block_identifier: BlockIdentifier = 'latest',
    ) -> VaultTotalValueMap:
        """
        Calculates the Total Value (TV) across all staking vaults connected to the protocol.

        A validator is included in the TV calculation if EITHER of the following conditions is true:

        1. It has already passed activation eligibility: validator.activation_eligibility_epoch != FAR_FUTURE_EPOCH
            - add full balance + pending deposits are added to TV, as the validator is for sure will be activated
        2. If not-yet-eligible, then validator is checked over the registered PDG validator stages:
            - PREDEPOSITED: add 1 ETH to TV, as only the predeposit is counted and not the validator balance
            - ACTIVATED: count as `already passed activation`, thus add full balance + pending deposits to TV
            - all other stages are skipped as not related to the non-eligible for activation validators

        NB: In the PDG validator proving flow, a validator initially receives 1 ETH on the consensus layer as a
            predeposit. After the proof is submitted, an additional 31 ETH immediately appears on the consensus layer
            as a pending deposit. If we ignore these pending deposits, vault's TV would appear to drop by 32 ETH
            until the pending deposit is finalized and the validator is activated. To avoid this misleading drop,
            the calculation of a validator's total balance must include all pending deposits, but only for those
            validators that passed PDG flow. All side-deposited validators will appear in the TV as soon as the
            validator becomes eligible for activation.
        """
        validators_by_vault = self._get_validators_by_vault(validators, vaults)
        total_pending_amount_by_pubkey = self._get_total_pending_amount_by_pubkey(pending_deposits)
        inactive_validator_statuses = self._get_non_activated_validator_stages(validators, vaults, block_identifier)

        total_values: VaultTotalValueMap = {}
        for vault_address, vault in vaults.items():
            vault_total: int = int(vault.aggregated_balance)

            for validator in validators_by_vault.get(vault_address, []):
                validator_pubkey = validator.pubkey.to_0x_hex()
                validator_pending_amount = total_pending_amount_by_pubkey.get(validator_pubkey, Gwei(0))
                total_validator_balance = gwei_to_wei(Gwei(validator.balance + validator_pending_amount))

                # Include validator balance and all pending deposits in TV when validator is eligible for activation or
                # has already passed activation
                if not has_far_future_activation_eligibility_epoch(validator.validator):
                    vault_total += int(total_validator_balance)

                # For not-yet-eligible validators, use PDG stages:
                # - PREDEPOSITED: add 1 ETH (guaranteed)
                # - ACTIVATED: add full balance + pending deposits
                # All other stages are skipped as not related to the non-eligible for activation validators
                else:
                    status = inactive_validator_statuses.get(validator_pubkey)
                    # Skip if validator pubkey in PDG is not associated with the current vault
                    if status is None or status.staking_vault != vault_address:
                        continue

                    if status.stage == ValidatorStage.PREDEPOSITED:
                        vault_total += int(gwei_to_wei(MIN_DEPOSIT_AMOUNT))
                    elif status.stage == ValidatorStage.ACTIVATED:
                        vault_total += int(total_validator_balance)

            total_values[vault_address] = Wei(vault_total)
            logger.info({
                'msg': f'Calculate vault TVL: {vault_address}.',
                'value': total_values[vault_address],
            })

        return total_values

    def _get_non_activated_validator_stages(
        self,
        validators: list[Validator],
        vaults: VaultsMap,
        block_identifier: BlockIdentifier = 'latest',
    ) -> dict[str, ValidatorStatus]:
        """
        Get PDG validator stages for non-activated validators for connected vaults from the lazy oracle.
        """

        vault_wcs = {v.withdrawal_credentials for v in vaults.values()}
        pubkeys = [
            v.pubkey.to_0x_hex()
            for v in validators
            if has_far_future_activation_eligibility_epoch(v.validator)
            and v.validator.withdrawal_credentials in vault_wcs
        ]

        return self.w3.lido_contracts.lazy_oracle.get_validator_statuses(
            pubkeys=pubkeys,
            block_identifier=block_identifier,
        )

    @staticmethod
    def _get_total_pending_amount_by_pubkey(
        pending_deposits: list[PendingDeposit],
    ) -> dict[str, Gwei]:
        deposits: defaultdict[str, int] = defaultdict(int)
        for deposit in pending_deposits:
            deposits[deposit.pubkey] += int(deposit.amount)

        return {pubkey: Gwei(deposits[pubkey]) for pubkey in deposits}

    @staticmethod
    def _get_validators_by_vault(validators: list[Validator], vaults: VaultsMap) -> VaultToValidators:
        """
        Groups validators by their associated vault, based on withdrawal credentials.
        """
        wc_to_vault: dict[str, VaultInfo] = {v.withdrawal_credentials: v for v in vaults.values()}

        vault_to_validators: VaultToValidators = defaultdict(list)
        for validator in validators:
            wc = validator.validator.withdrawal_credentials

            if vault_info := wc_to_vault.get(wc):
                vault_to_validators[vault_info.vault].append(validator)

        return vault_to_validators

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
        validators_by_vault = self._get_validators_by_vault(validators, vaults)
        oracle_daemon_config = self.w3.lido_contracts.oracle_daemon_config

        slashing_reserve_we_left_shift = oracle_daemon_config.slashing_reserve_we_left_shift(bs.block_hash)
        slashing_reserve_we_right_shift = oracle_daemon_config.slashing_reserve_we_right_shift(bs.block_hash)

        def calc_reserve(balance: Wei, reserve_ratio_bp: int) -> int:
            out = Decimal(balance) * Decimal(reserve_ratio_bp) / Decimal(TOTAL_BASIS_POINTS)
            return int(out.to_integral_value(ROUND_UP))

        vaults_reserves: VaultReserveMap = defaultdict(int)
        for vault_address, vault_validators in validators_by_vault.items():
            for validator in vault_validators:
                if validator.validator.slashed:
                    withdrawable_epoch = validator.validator.withdrawable_epoch

                    if (
                        withdrawable_epoch - slashing_reserve_we_left_shift
                        <= bs.ref_epoch
                        <= withdrawable_epoch + slashing_reserve_we_right_shift
                    ):
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

        return self.w3.ipfs.publish(dumped_tree_str.encode('ascii'), MERKLE_TREE_VAULTS_FILENAME)

    @staticmethod
    def get_dumped_tree(
        tree: StandardMerkleTree,
        vaults: VaultsMap,
        bs: ReferenceBlockStamp,
        prev_tree_cid: str,
        chain_config: ChainConfig,
        vaults_fee_map: VaultFeeMap,
    ) -> dict[str, Any]:
        def stringify_values(data) -> list[dict[str, str | int]]:
            out = []
            for item in data:
                out.append({
                    "value": (item["value"][0],) + tuple(str(x) for x in item["value"][1:]),
                    "treeIndex": item["treeIndex"],
                })
            return out

        values = stringify_values(tree.values)

        extra_values = {}
        for vault_adr, vault_info in vaults.items():
            extra_values[vault_adr] = ExtraValue(
                in_out_delta=str(vault_info.in_out_delta),
                prev_fee=str(vaults_fee_map[vault_adr].prev_fee),
                infra_fee=str(vaults_fee_map[vault_adr].infra_fee),
                liquidity_fee=str(vaults_fee_map[vault_adr].liquidity_fee),
                reservation_fee=str(vaults_fee_map[vault_adr].reservation_fee),
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

    def get_ipfs_report(self, ipfs_report_cid: str, current_frame: FrameNumber) -> StakingVaultIpfsReport:
        if ipfs_report_cid == "":
            raise ValueError("Arg ipfs_report_cid could not be ''")
        return self.get_vault_report(ipfs_report_cid, current_frame)

    def get_vault_report(self, tree_cid: str, current_frame: FrameNumber) -> StakingVaultIpfsReport:
        bb = self.w3.ipfs.fetch(CID(tree_cid), current_frame)
        return StakingVaultIpfsReport.parse_merkle_tree_data(bb)

    def get_latest_onchain_ipfs_report_data(self, block_identifier: BlockIdentifier) -> OnChainIpfsVaultReportData:
        return self.w3.lido_contracts.lazy_oracle.get_latest_report_data(block_identifier)

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

            tree_data.append((
                vault_address,
                Wei(vaults_total_values[vault_address]),
                vaults_fees[vault_address].total(),
                vault.liability_shares,
                vault.max_liability_shares,
                vaults_slashing_reserve.get(vault_address, 0),
            ))

        return tree_data

    @staticmethod
    def get_merkle_tree(data: list[VaultTreeNode]) -> StandardMerkleTree:
        return StandardMerkleTree(data, ("address", "uint256", "uint256", "uint256", "uint256", "uint256"))

    def is_tree_root_valid(self, expected_tree_root: str, merkle_tree: StakingVaultIpfsReport) -> bool:
        tree_data = []
        for vault in merkle_tree.values:
            tree_data.append((
                vault.vault_address,
                vault.total_value_wei,
                vault.fee,
                vault.liability_shares,
                vault.max_liability_shares,
                vault.slashing_reserve,
            ))

        rebuild_merkle_tree = self.get_merkle_tree(tree_data)
        root_hex = f'0x{rebuild_merkle_tree.root.hex()}'
        return merkle_tree.tree[0] == root_hex and root_hex == expected_tree_root

    @staticmethod
    def calc_fee_value(value: Decimal, block_elapsed: int, core_apr_ratio: Decimal, fee_bp: int) -> Decimal:
        return (
            value
            * Decimal(block_elapsed)
            * core_apr_ratio
            * Decimal(fee_bp)
            / Decimal(BLOCKS_PER_YEAR * TOTAL_BASIS_POINTS)
        )

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
            sort_events(events[vault_address])

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
        current_frame: FrameNumber,
    ) -> tuple[Optional[StakingVaultIpfsReport], BlockNumber]:
        slots_per_frame = frame_config.epochs_per_frame * chain_config.slots_per_epoch
        accounting_oracle = self.w3.lido_contracts.accounting_oracle

        if latest_onchain_ipfs_report_data.report_cid != "":
            prev_ipfs_report = self.get_ipfs_report(latest_onchain_ipfs_report_data.report_cid, current_frame)
            tree_root_hex = Web3.to_hex(latest_onchain_ipfs_report_data.tree_root)

            if not self.is_tree_root_valid(tree_root_hex, prev_ipfs_report):
                raise ValueError(
                    f"Invalid tree root in IPFS report data. "
                    f"Expected: {tree_root_hex}, actual: {prev_ipfs_report.tree[0]}"
                )

            last_processing_ref_slot = accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)
            ref_block = get_blockstamp(
                self.w3.cc, last_processing_ref_slot, SlotNumber(int(last_processing_ref_slot) + slots_per_frame)
            )

            # Prevent double-counting of vault events:
            # If any vault-related event occurred in the same block as the previous IPFS report,
            # it has already been included in that report. To avoid overlapping calculations,
            # we shift the starting point by one block forward.
            return prev_ipfs_report, ref_block.block_number + 1

        ## When we do NOT HAVE prev IPFS report => we have to check two branches: for mainnet and devnet (genesis vaults support)
        ## Mainnet
        ##   in case when we don't have prev ipfs report - we DO have previous oracle report
        ##   it means we have to take this point for getting fees at the FIRST time only
        last_processing_ref_slot = accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)
        if last_processing_ref_slot:
            ref_block = get_blockstamp(
                self.w3.cc, last_processing_ref_slot, SlotNumber(int(last_processing_ref_slot) + slots_per_frame)
            )
            return None, ref_block.block_number + 1

        ## Fresh devnet
        ## We DO not have prev IPFS report, and we DO not have prev Oracle report then we take
        # If skipped, we reference the block from the first non-missed slot (frame length offset presumes availability).
        initial_ref_slot = frame_config.initial_epoch * chain_config.slots_per_epoch
        bs = get_blockstamp(
            self.w3.cc, SlotNumber(initial_ref_slot), SlotNumber(int(initial_ref_slot + slots_per_frame))
        )
        return None, bs.block_number

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
        current_frame: FrameNumber,
    ) -> VaultFeeMap:
        prev_ipfs_report, prev_block_number = self._get_start_point_for_fee_calculations(
            blockstamp, latest_onchain_ipfs_report_data, frame_config, chain_config, current_frame
        )

        vault_hub = self.w3.lido_contracts.vault_hub
        prev_fee_map = defaultdict(int)
        prev_liability_shares_map = defaultdict(int)
        if prev_ipfs_report is not None:
            for vault in prev_ipfs_report.values:
                prev_fee_map[vault.vault_address] = vault.fee
                prev_liability_shares_map[vault.vault_address] = vault.liability_shares

        events: defaultdict[str, list[VaultEventType]] = defaultdict(list)
        vault_connected_events = vault_hub.get_vault_connected_events(prev_block_number, blockstamp.block_number)
        fees_updated_events = vault_hub.get_vault_fee_updated_events(prev_block_number, blockstamp.block_number)
        minted_events = vault_hub.get_minted_events(prev_block_number, blockstamp.block_number)
        burn_events = vault_hub.get_burned_events(prev_block_number, blockstamp.block_number)
        rebalanced_events = vault_hub.get_vault_rebalanced_events(prev_block_number, blockstamp.block_number)
        bad_debt_socialized_events = vault_hub.get_bad_debt_socialized_events(
            prev_block_number, blockstamp.block_number
        )
        written_off_to_be_internalized_events = vault_hub.get_bad_debt_written_off_to_be_internalized_events(
            prev_block_number, blockstamp.block_number
        )

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

        connected_vaults_set = set()
        for vault_connected_event in vault_connected_events:
            events[vault_connected_event.vault].append(vault_connected_event)
            connected_vaults_set.add(vault_connected_event.vault)

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

            vault_got_connected_event = vault_address in connected_vaults_set

            ## If the vault was disconnected and then reconnected between reports,
            ## we must not carry over liability_shares from the previous report.
            ##
            ## The fees were already paid, and the vault essentially starts a new lifecycle from zero.
            prev_liability_shares = prev_liability_shares_map[vault_address]
            if vault_got_connected_event:
                prev_liability_shares = 0

            if prev_liability_shares != liability_shares:
                raise ValueError(
                    f"Wrong liability shares by vault {vault_address}. Actual {liability_shares} != Expected {prev_liability_shares}"
                )

            out[vault_address] = VaultFee(
                prev_fee=int(0) if vault_got_connected_event else int(prev_fee_map[vault_address]),
                infra_fee=int(vault_infrastructure_fee.to_integral_value(ROUND_UP)),
                reservation_fee=int(vault_reservation_liquidity_fee.to_integral_value(ROUND_UP)),
                liquidity_fee=int(vault_liquidity_fee.to_integral_value(ROUND_UP)),
            )

        return out
