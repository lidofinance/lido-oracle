import json
import logging
from collections import defaultdict
from dataclasses import asdict
from decimal import ROUND_UP, Decimal
from typing import Any, Optional

from eth_typing import BlockNumber, ChecksumAddress
from oz_merkle_tree import StandardMerkleTree
from web3.types import BlockIdentifier, Wei

from src import variables
from src.constants import (
    MIN_DEPOSIT_AMOUNT,
    SECONDS_IN_YEAR,
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
)
from src.modules.accounting.types import (
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
from src.providers.execution.contracts.accounting_oracle import AccountingOracleContract
from src.providers.execution.contracts.vault_hub import VaultHubContract
from src.providers.ipfs import CID
from src.types import FrameNumber, Gwei, ReferenceBlockStamp, SlotNumber
from src.utils.apr import get_steth_by_shares
from src.utils.block import get_block_timestamps
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

        1. For each validator, if activation_eligibility_epoch != FAR_FUTURE_EPOCH
            TV += validator.balance + pending_deposits

        2. For each validator, if activation_eligibility_epoch == FAR_FUTURE_EPOCH
            TV += (depending on PDG stage)

        ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
        │ PDG STAGE          │  NONE  │  PREDEPOSITED  │     PROVEN     │    ACTIVATED    │   COMPENSATED │
        │ ───────────────────┼────────┼────────────────┼────────────────┼─────────────────┼────────────── │
        │ TV CONTRIBUTION    │   0    │     1 ETH      │       0        │  balance + pend │      0        │
        └─────────────────────────────────────────────────────────────────────────────────────────────────┘

        3. For each pending deposit, if pubkey is not associated with any validator
            TV += 1 ETH if PDG stage is PREDEPOSITED (only once per pubkey, to avoid double-counting)

           * pending deposits can't be ACTIVATED on PDG, as activation happens only for created validators.

        NB: In the PDG validator proving process, a validator initially receives 1 ETH on the consensus layer as a
            predeposit (PREDEPOSITED). Once the proof is submitted, an additional 31 ETH immediately shows up on the
            consensus layer as a pending deposit (ACTIVATED). Ignoring these pending deposits would make the vault's TV
            appear to decrease by 32 ETH until the deposit is finalized and the validator is activated. To prevent this
            misleading drop, the TV calculation should include all pending deposits, but only for validators that have
            passed the PDG flow. All validators with side-deposits will be reflected in the TV as soon as they are
            eligible for activation.
        """
        validators_by_vault = self._get_validators_by_vault(validators, vaults)
        total_pending_amount_by_pubkey = self._get_total_pending_amount_by_pubkey(pending_deposits)

        vault_wcs = {v.withdrawal_credentials for v in vaults.values()}

        non_eligible_pubkeys = self._get_non_eligible_for_activation_validators_pubkeys(validators, vault_wcs)
        validator_statuses_by_vault = self._get_pubkey_statuses_by_vault(
            pubkeys=non_eligible_pubkeys,
            block_identifier=block_identifier,
        )

        unmatched_pubkeys = self._get_unmatched_deposits_pubkeys(validators, pending_deposits, vault_wcs)
        unmatched_pending_deposits_statuses_by_vault = self._get_pubkey_statuses_by_vault(
            pubkeys=unmatched_pubkeys,
            block_identifier=block_identifier,
        )

        total_values: VaultTotalValueMap = {}
        for vault_address, vault in vaults.items():
            vault_total = self._calculate_vault_total_value(
                vault_aggregated_balance=vault.aggregated_balance,
                vault_validators=validators_by_vault.get(vault_address, []),
                total_pending_amount_by_pubkey=total_pending_amount_by_pubkey,
                vault_validator_statuses=validator_statuses_by_vault.get(vault_address, {}),
                vault_unmatched_pending_deposit_statuses=unmatched_pending_deposits_statuses_by_vault.get(vault_address, {}),
            )

            total_values[vault_address] = Wei(vault_total)
            logger.info({
                'msg': f'Calculate vault TVL: {vault_address}.',
                'value': total_values[vault_address],
            })

        return total_values

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

    @staticmethod
    def _get_total_pending_amount_by_pubkey(pending_deposits: list[PendingDeposit]) -> dict[str, Gwei]:
        """
        Calculates the total pending amount for each pubkey.
        """
        deposits: defaultdict[str, int] = defaultdict(int)
        for deposit in pending_deposits:
            deposits[deposit.pubkey] += int(deposit.amount)

        return {pubkey: Gwei(deposits[pubkey]) for pubkey in deposits}

    @staticmethod
    def _get_non_eligible_for_activation_validators_pubkeys(validators: list[Validator], vault_wcs: set[str]) -> set[str]:
        """
        Get set of pubkeys of non-eligible for activation validators that are associated with the vaults.
        """
        return {
            v.validator.pubkey
            for v in validators
            if has_far_future_activation_eligibility_epoch(v.validator)
               and v.validator.withdrawal_credentials in vault_wcs
        }

    @staticmethod
    def _get_unmatched_deposits_pubkeys(
        validators: list[Validator],
        pending_deposits: list[PendingDeposit],
        vault_wcs: set[str]
    ) -> set[str]:
        """
        Get set of pubkeys of pending deposits that are associated with the vaults and do not have matching validator.
        """
        all_validator_pubkeys = {v.validator.pubkey for v in validators}
        return {
            deposit.pubkey
            for deposit in pending_deposits
            if deposit.withdrawal_credentials in vault_wcs and deposit.pubkey not in all_validator_pubkeys
        }

    def _get_pubkey_statuses_by_vault(
        self,
        pubkeys: set[str],
        block_identifier: BlockIdentifier,
    ) -> dict[str, dict[str, ValidatorStatus]]:
        """
        Fetches validator statuses from the PDG for the given pubkeys.
        """
        statuses = self.w3.lido_contracts.lazy_oracle.get_validator_statuses(
            pubkeys=list(pubkeys),
            block_identifier=block_identifier,
            batch_size=variables.VAULT_VALIDATOR_STATUSES_BATCH_SIZE,
        )

        statuses_by_vault: dict[str, dict[str, ValidatorStatus]] = defaultdict(dict)
        for pubkey, status in statuses.items():
            statuses_by_vault[status.staking_vault][pubkey] = status

        return statuses_by_vault

    @staticmethod
    def _calculate_vault_total_value(
        vault_aggregated_balance: Wei,
        vault_validators: list[Validator],
        total_pending_amount_by_pubkey: dict[str, Gwei],
        vault_validator_statuses: dict[str, ValidatorStatus],
        vault_unmatched_pending_deposit_statuses: dict[str, ValidatorStatus],
    ) -> int:
        """
        Calculates total value for a single vault.

        Starting point:
        ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
        │                               Vault Aggregated Balance (Execution Layer)                                    │
        │                                 Initial TV = vault.aggregated_balance                                       │
        └─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                          │
                                     Validators and Pending Deposits Contributions
                                                          │
                     ┌────────────────────────────────────┼────────────────────────────────────┐
                     │                                    │                                    │
                     ▼                                    ▼                                    ▼
            ┌─────────────────────────┐        ┌─────────────────────────┐        ┌─────────────────────────┐
            │   ELIGIBLE VALIDATORS   │        │ NON-ELIGIBLE VALIDATORS │        │  UNMATCHED PENDING      │
            │                         │        │                         │        │  DEPOSITS               │
            │  activation_elig ≠      │        │  activation_elig =      │        │                         │
            │  FAR_FUTURE_EPOCH       │        │  FAR_FUTURE_EPOCH       │        │  (pubkey not in any     │
            │                         │        │                         │        │    vault validator)     │
            └─────────────────────────┘        └─────────────────────────┘        └─────────────────────────┘
                     │                                    │                                    │
                     │                                    │                                    │
                     ▼                                    ▼                                    ▼
            ┌─────────────────────────┐        ┌─────────────────────────┐        ┌─────────────────────────┐
            │  Add FULL value:        │        │  Check PDG Stage:       │        │  Check PDG Stage:       │
            │                         │        │                         │        │                         │
            │  TV += balance +        │        │  • PREDEPOSITED         │        │  • PREDEPOSITED         │
            │        pendings         │        │    TV += 1 ETH          │        │    TV += 1 ETH          │
            │                         │        │          (guaranteed)   │        │          (guaranteed)   │
            └─────────────────────────┘        │                         │        │                         │
                                               │  • ACTIVATED            │        │  • Other stages         │
                                               │    TV += balance +      │        │    └─► Skip             │
                                               │          pendings       │        │                         │
                                               │                         │        └─────────────────────────┘
                                               │  • Other stages         │
                                               │    └─► Skip             │
                                               └─────────────────────────┘
                      │                                    │                                    │
                      └────────────────────────────────────┼────────────────────────────────────┘
                                                           │
                                                           ▼
                                        ┌───────────────────────────────────────┐
                                        │    FINAL VAULT TOTAL VALUE (TV)       │
                                        └───────────────────────────────────────┘

        """
        vault_total = int(vault_aggregated_balance)

        for validator in vault_validators:
            validator_pubkey = validator.validator.pubkey
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
                status = vault_validator_statuses.get(validator_pubkey)
                # Skip if validator pubkey not found in PDG
                if status is None:
                    continue

                if status.stage == ValidatorStage.PREDEPOSITED:
                    vault_total += int(gwei_to_wei(MIN_DEPOSIT_AMOUNT))
                elif status.stage == ValidatorStage.ACTIVATED:
                    vault_total += int(total_validator_balance)

        # Only sum 1 ETH for unmatched pending deposits in PREDEPOSITED stage
        num_predeposited = sum(
            status.stage == ValidatorStage.PREDEPOSITED
            for status in vault_unmatched_pending_deposit_statuses.values()
        )

        vault_total += num_predeposited * int(gwei_to_wei(MIN_DEPOSIT_AMOUNT))

        return vault_total

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
    def calc_fee_value(value: Decimal, time_elapsed_seconds: int, core_apr_ratio: Decimal, fee_bp: int) -> Decimal:
        """Compute fee value over elapsed seconds using core APR and basis points."""
        return (
            value
            * Decimal(time_elapsed_seconds)
            * core_apr_ratio
            * Decimal(fee_bp)
            / Decimal(SECONDS_IN_YEAR * TOTAL_BASIS_POINTS)
        )

    @staticmethod
    def _apply_event(
        event: VaultEventType,
        vault_address: str,
        liability_shares: Shares,
        liquidity_fee: int,
    ) -> tuple[Shares, int]:
        """Apply event in reverse chronological order, returning updated shares and fee."""
        shares_delta = 0
        new_fee = liquidity_fee

        if isinstance(event, VaultFeesUpdatedEvent):
            new_fee = event.pre_liquidity_fee_bp
        elif isinstance(event, MintedSharesOnVaultEvent):
            shares_delta = -event.amount_of_shares
        elif isinstance(event, BurnedSharesOnVaultEvent):
            shares_delta = event.amount_of_shares
        elif isinstance(event, VaultRebalancedEvent):
            shares_delta = event.shares_burned
        elif isinstance(event, BadDebtWrittenOffToBeInternalizedEvent):
            shares_delta = event.bad_debt_shares
        elif isinstance(event, BadDebtSocializedEvent):
            shares_delta = event.bad_debt_shares if vault_address == event.vault_donor else -event.bad_debt_shares

        return liability_shares + shares_delta, new_fee  # type: ignore[return-value]

    @staticmethod
    def _get_report_timestamp(ref_slot: SlotNumber, chain_config: ChainConfig) -> int:
        """Convert a ref slot to a report timestamp (start of slot, in seconds)."""
        return chain_config.genesis_time + int(ref_slot) * chain_config.seconds_per_slot

    @staticmethod
    def _calculate_liquidity_fee_by_events(
        vault_address: str,
        liability_shares: Shares,
        liquidity_fee_bp: int,
        vault_events: list[VaultEventType],
        prev_ref_slot_timestamp: int,
        current_ref_slot_timestamp: int,
        pre_total_pooled_ether: Wei,
        pre_total_shares: Shares,
        core_apr_ratio: Decimal,
        block_timestamps: dict[BlockNumber, int],
    ) -> tuple[Decimal, Shares]:
        """
        Liquidity fee = Minted_stETH × Lido_Core_APR × Liquidity_fee_rate

        We calculate the liquidity fee for the vault as a series of time intervals
        between vault events (mints, burns, fee updates, rebalances, bad debt events).
        All events use their block's execution timestamp directly.

        Events are processed in reverse chronological order (backward in time) to
        reconstruct the liability_shares at each point in time. The fee accrual is
        calculated for each interval between consecutive events.

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
                └─────────────────┴──────────────┴───────────┴────────▶ time (seconds)

                                 mintEvent      burnEvent  current_block

                        ◄─────────────────────── processing backwards in time
        """
        vault_liquidity_fee = Decimal(0)
        liquidity_fee = liquidity_fee_bp
        # Track the boundary from the last processed event/report as we walk backward.
        prev_event_timestamp = current_ref_slot_timestamp

        # We iterate through events backwards, calculating liquidity fee for each interval based
        # on the `liability_shares` and the elapsed time between events.
        # Sort by (block_number, log_index) in reverse order to process events backwards in time.
        vault_events.sort(key=lambda e: (e.block_number, e.log_index), reverse=True)

        for event in vault_events:
            if event.block_number not in block_timestamps:
                raise ValueError(f"Missing timestamp for block {event.block_number}")
            event_timestamp = block_timestamps[event.block_number]
            interval_seconds = prev_event_timestamp - event_timestamp
            if interval_seconds < 0:
                raise ValueError(
                    f"Negative event interval for vault {vault_address}. "
                    f"{prev_event_timestamp=} {event_timestamp=}"
                )
            minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
            vault_liquidity_fee += StakingVaultsService.calc_fee_value(
                minted_steth_on_event, interval_seconds, core_apr_ratio, liquidity_fee
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
            liability_shares, liquidity_fee = StakingVaultsService._apply_event(
                event=event,
                vault_address=vault_address,
                liability_shares=liability_shares,
                liquidity_fee=liquidity_fee,
            )

            prev_event_timestamp = event_timestamp

        interval_seconds = prev_event_timestamp - prev_ref_slot_timestamp
        if interval_seconds < 0:
            raise ValueError(
                f"Negative event interval for vault {vault_address}. "
                f"{prev_event_timestamp=} {prev_ref_slot_timestamp=}"
            )

        minted_steth_on_event = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
        vault_liquidity_fee += StakingVaultsService.calc_fee_value(
            minted_steth_on_event, interval_seconds, core_apr_ratio, liquidity_fee
        )

        return vault_liquidity_fee, liability_shares

    def _get_prev_vault_ipfs_report(
        self,
        latest_onchain_ipfs_report_data: OnChainIpfsVaultReportData,
        current_frame: FrameNumber,
    ) -> Optional[StakingVaultIpfsReport]:
        """
        Fetch and validate the previous IPFS report if available.

        Returns the parsed previous IPFS report, or None if not available.
        """
        if latest_onchain_ipfs_report_data.report_cid == "":
            return None

        prev_ipfs_report = self.get_ipfs_report(latest_onchain_ipfs_report_data.report_cid, current_frame)
        tree_root_hex = Web3.to_hex(latest_onchain_ipfs_report_data.tree_root)

        if not self.is_tree_root_valid(tree_root_hex, prev_ipfs_report):
            raise ValueError(
                f"Invalid tree root in IPFS report data. "
                f"Expected: {tree_root_hex}, actual: {prev_ipfs_report.tree[0]}"
            )

        return prev_ipfs_report

    @staticmethod
    def _build_prev_report_maps(
        prev_ipfs_report: Optional[StakingVaultIpfsReport],
    ) -> tuple[defaultdict[ChecksumAddress, int], defaultdict[ChecksumAddress, int]]:
        """Build lookup maps for previous fees and liability shares from the last report."""
        prev_fee_map: defaultdict[ChecksumAddress, int] = defaultdict(int)
        prev_liability_shares_map: defaultdict[ChecksumAddress, int] = defaultdict(int)
        if prev_ipfs_report is not None:
            for vault in prev_ipfs_report.values:
                prev_fee_map[vault.vault_address] = vault.fee
                prev_liability_shares_map[vault.vault_address] = vault.liability_shares
        return prev_fee_map, prev_liability_shares_map

    def _get_vault_events_for_fees(
        self,
        vault_hub: VaultHubContract,
        from_block: BlockNumber,
        to_block: BlockNumber,
    ) -> tuple[defaultdict[str, list[VaultEventType]], set[str]]:
        """
        Fetch vault events over [from_block, to_block] and group them by vault address.

        Returns events_by_vault and a set of vaults that reconnected in the interval.
        """
        events: defaultdict[str, list[VaultEventType]] = defaultdict(list)
        connected_vaults_set: set[str] = set()

        for fees_updated_event in vault_hub.get_vault_fee_updated_events(from_block, to_block):
            events[fees_updated_event.vault].append(fees_updated_event)

        for minted_event in vault_hub.get_minted_events(from_block, to_block):
            events[minted_event.vault].append(minted_event)

        for burned_event in vault_hub.get_burned_events(from_block, to_block):
            events[burned_event.vault].append(burned_event)

        for rebalanced_event in vault_hub.get_vault_rebalanced_events(from_block, to_block):
            events[rebalanced_event.vault].append(rebalanced_event)

        for written_off_event in vault_hub.get_bad_debt_written_off_to_be_internalized_events(from_block, to_block):
            events[written_off_event.vault].append(written_off_event)

        for socialized_event in vault_hub.get_bad_debt_socialized_events(from_block, to_block):
            events[socialized_event.vault_donor].append(socialized_event)
            events[socialized_event.vault_acceptor].append(socialized_event)

        for vault_connected_event in vault_hub.get_vault_connected_events(from_block, to_block):
            events[vault_connected_event.vault].append(vault_connected_event)
            connected_vaults_set.add(vault_connected_event.vault)

        return events, connected_vaults_set

    @staticmethod
    def _calculate_vault_fee_components(
        vault_address: ChecksumAddress,
        vault_info: VaultInfo,
        vault_total_value: int,
        vault_events: list[VaultEventType],
        report_interval_seconds: int,
        prev_ref_slot_timestamp: int,
        current_ref_slot_timestamp: int,
        core_apr_ratio: Decimal,
        pre_total_pooled_ether: Wei,
        pre_total_shares: Shares,
        block_timestamps: dict[BlockNumber, int],
    ) -> tuple[Decimal, Decimal, Decimal, Shares]:
        """Calculate infra, reservation, and liquidity fees for a single vault."""
        # Infrastructure fee = Total_value * Lido_Core_APR * Infrastructure_fee_rate
        vault_infrastructure_fee = StakingVaultsService.calc_fee_value(
            value=Decimal(vault_total_value),
            time_elapsed_seconds=report_interval_seconds,
            core_apr_ratio=core_apr_ratio,
            fee_bp=vault_info.infra_fee_bp,
        )

        # Mintable_stETH * Lido_Core_APR * Reservation_liquidity_fee_rate
        vault_reservation_liquidity_fee = StakingVaultsService.calc_fee_value(
            value=Decimal(vault_info.mintable_st_eth),
            time_elapsed_seconds=report_interval_seconds,
            core_apr_ratio=core_apr_ratio,
            fee_bp=vault_info.reservation_fee_bp,
        )

        # If there are no events for this vault, we just use the liability shares to compute minted stETH.
        if not vault_events:
            liability_shares = vault_info.liability_shares
            minted_steth = get_steth_by_shares(liability_shares, pre_total_pooled_ether, pre_total_shares)
            vault_liquidity_fee = StakingVaultsService.calc_fee_value(
                value=minted_steth,
                time_elapsed_seconds=report_interval_seconds,
                core_apr_ratio=core_apr_ratio,
                fee_bp=vault_info.liquidity_fee_bp,
            )

            return vault_infrastructure_fee, vault_reservation_liquidity_fee, vault_liquidity_fee, liability_shares

        # If there are events for this vault, we calculate the liquidity fee using the event-based helper.
        vault_liquidity_fee, liability_shares = StakingVaultsService._calculate_liquidity_fee_by_events(
            vault_address=vault_address,
            liability_shares=vault_info.liability_shares,
            liquidity_fee_bp=vault_info.liquidity_fee_bp,
            vault_events=vault_events,
            prev_ref_slot_timestamp=prev_ref_slot_timestamp,
            current_ref_slot_timestamp=current_ref_slot_timestamp,
            pre_total_pooled_ether=pre_total_pooled_ether,
            pre_total_shares=pre_total_shares,
            core_apr_ratio=core_apr_ratio,
            block_timestamps=block_timestamps,
        )

        return vault_infrastructure_fee, vault_reservation_liquidity_fee, vault_liquidity_fee, liability_shares

    def get_vaults_fees(
        self,
        blockstamp: ReferenceBlockStamp,
        vaults: VaultsMap,
        vaults_total_values: VaultTotalValueMap,
        latest_onchain_ipfs_report_data: OnChainIpfsVaultReportData,
        core_apr_ratio: Decimal,
        pre_total_pooled_ether: Wei,
        pre_total_shares: Shares,
        frame_config: FrameConfig,
        chain_config: ChainConfig,
        current_frame: FrameNumber,
    ) -> VaultFeeMap:
        accounting_oracle: AccountingOracleContract = self.w3.lido_contracts.accounting_oracle
        vault_hub: VaultHubContract = self.w3.lido_contracts.vault_hub

        prev_ipfs_report = self._get_prev_vault_ipfs_report(
            latest_onchain_ipfs_report_data=latest_onchain_ipfs_report_data,
            current_frame=current_frame,
        )

        # Calculate from block param
        from_ref_slot: SlotNumber = accounting_oracle.get_last_processing_ref_slot(blockstamp.block_hash)

        # If this is first report
        if not from_ref_slot:
            # Time range should include all events from FrameIndex 0 upto current ref slot
            # Calculate FrameIndex 0 ref slot
            potential_prev_ref_slot = (frame_config.initial_epoch - frame_config.epochs_per_frame) * chain_config.slots_per_epoch - 1
            from_ref_slot = SlotNumber(max(potential_prev_ref_slot, 0))

        prev_report_block_number = get_blockstamp(
            cc=self.w3.cc,
            slot=from_ref_slot,
            last_finalized_slot_number=blockstamp.slot_number,
        ).block_number

        # Events are fetched forward over (event_start_block, current_block] and applied backward by timestamp.
        events, connected_vaults_set = self._get_vault_events_for_fees(
            vault_hub=vault_hub,
            # Do not include events from last block of last frame
            from_block=prev_report_block_number + 1,
            to_block=blockstamp.block_number,
        )

        # Missed CL slots produce no EL blocks, so elapsed time must be derived from ref slots.
        current_ref_slot_timestamp = self._get_report_timestamp(blockstamp.ref_slot, chain_config)
        prev_ref_slot_timestamp = self._get_report_timestamp(from_ref_slot, chain_config)
        report_interval_seconds = current_ref_slot_timestamp - prev_ref_slot_timestamp
        if report_interval_seconds < 0:
            raise ValueError(
                "Negative report interval."
                f" {current_ref_slot_timestamp=} {prev_ref_slot_timestamp=} {blockstamp.ref_slot=} {from_ref_slot=}"
            )

        prev_fee_map, prev_liability_shares_map = self._build_prev_report_maps(prev_ipfs_report)
        out: VaultFeeMap = {}

        event_block_numbers = {event.block_number for vault_events in events.values() for event in vault_events}
        block_timestamps = get_block_timestamps(self.w3, event_block_numbers, chain_config.seconds_per_slot)

        for vault_address, vault_info in vaults.items():
            ## If the vault was disconnected and then reconnected between reports,
            ## we must not carry over liability_shares from the previous report.
            ##
            ## The fees were already paid, and the vault essentially starts a new lifecycle from zero.
            prev_liability_shares = prev_liability_shares_map[vault_address]
            prev_fee = prev_fee_map[vault_address]
            if vault_address in connected_vaults_set:
                prev_liability_shares = 0
                prev_fee = 0

            vault_events = events.get(vault_address, [])
            vaults_total_value = vaults_total_values.get(vault_address, 0)

            (
                vault_infrastructure_fee,
                vault_reservation_liquidity_fee,
                vault_liquidity_fee,
                vault_liability_shares,
            ) = self._calculate_vault_fee_components(
                vault_address=vault_address,
                vault_info=vault_info,
                vault_total_value=vaults_total_value,
                vault_events=vault_events,
                report_interval_seconds=report_interval_seconds,
                prev_ref_slot_timestamp=prev_ref_slot_timestamp,
                current_ref_slot_timestamp=current_ref_slot_timestamp,
                core_apr_ratio=core_apr_ratio,
                pre_total_pooled_ether=pre_total_pooled_ether,
                pre_total_shares=pre_total_shares,
                block_timestamps=block_timestamps,
            )

            if prev_liability_shares != vault_liability_shares:
                raise ValueError(
                    f"Wrong liability shares by vault {vault_address}. "
                    f"Actual {vault_liability_shares} != Expected {prev_liability_shares}"
                )

            out[vault_address] = VaultFee(
                prev_fee=int(prev_fee),
                infra_fee=int(vault_infrastructure_fee.to_integral_value(ROUND_UP)),
                reservation_fee=int(vault_reservation_liquidity_fee.to_integral_value(ROUND_UP)),
                liquidity_fee=int(vault_liquidity_fee.to_integral_value(ROUND_UP)),
            )

        return out
