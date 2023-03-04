import logging
import math
from dataclasses import dataclass
from typing import Mapping, Any

from web3.types import Wei, EventData

from src.constants import MAX_EFFECTIVE_BALANCE
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey
from src.services.bunker_cases.typings import BunkerConfig
from src.typings import ReferenceBlockStamp, Gwei, BlockStamp, EpochNumber, BlockNumber, SlotNumber
from src.utils.slot import get_first_non_missed_slot
from src.utils.validator_state import calculate_total_active_effective_balance
from src.web3py.extensions.lido_validators import LidoValidator
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class AbnormalClRebase:

    b_conf: BunkerConfig
    c_conf: ChainConfig
    last_report_ref_slot: SlotNumber
    all_validators: dict[str, Validator]
    lido_keys: dict[str, LidoKey]
    lido_validators: dict[str, LidoValidator]

    def __init__(self, w3: Web3):
        self.w3 = w3

    def is_abnormal_cl_rebase(self, blockstamp: ReferenceBlockStamp, frame_cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Checking abnormal CL rebase"})
        normal_cl_rebase = self._get_normal_cl_rebase(blockstamp)
        if frame_cl_rebase < normal_cl_rebase:
            logger.info({"msg": "Abnormal CL rebase in frame"})
            if self.b_conf.rebase_check_nearest_epoch_distance == 0 and self.b_conf.rebase_check_distant_epoch_distance == 0:
                logger.info({"msg": "Specific CL rebase calculation are disabled"})
                return True
            is_negative_specific_cl_rebase = self._is_negative_specific_cl_rebase(blockstamp)
            if is_negative_specific_cl_rebase:
                return True
        return False

    def _get_normal_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        """
        Calculate normal CL rebase (relative to all validators and the previous Lido frame)
        for current frame for Lido validators
        """
        last_report_blockstamp = get_first_non_missed_slot(
            self.w3.cc,
            self.last_report_ref_slot,
            ref_epoch=EpochNumber(self.last_report_ref_slot // self.c_conf.slots_per_epoch),
            last_finalized_slot_number=blockstamp.slot_number,
        )

        total_ref_effective_balance = calculate_total_active_effective_balance(
            self.all_validators, blockstamp.ref_epoch
        )
        total_ref_lido_effective_balance = calculate_total_active_effective_balance(
            self.lido_validators, blockstamp.ref_epoch
        )

        last_all_validators = {
            v.validator.pubkey: v for v in self.w3.cc.get_validators_no_cache(last_report_blockstamp)
        }

        last_lido_validators = self.w3.lido_validators.merge_validators_with_keys(
            list(self.lido_keys.values()),
            list(last_all_validators.values()),
        )

        last_lido_validators_dict = {v.validator.pubkey: v for v in last_lido_validators}

        total_last_effective_balance = calculate_total_active_effective_balance(
            last_all_validators, last_report_blockstamp.ref_epoch
        )
        total_last_lido_effective_balance = calculate_total_active_effective_balance(
            last_lido_validators_dict, last_report_blockstamp.ref_epoch
        )

        mean_total_effective_balance = (total_ref_effective_balance + total_last_effective_balance) // 2
        mean_total_lido_effective_balance = (
            (total_ref_lido_effective_balance + total_last_lido_effective_balance) // 2
        )

        epochs_passed = blockstamp.ref_epoch - last_report_blockstamp.ref_epoch

        normal_cl_rebase = self._calculate_normal_cl_rebase(
            epochs_passed, mean_total_lido_effective_balance, mean_total_effective_balance
        )

        logger.info({"msg": f"Normal CL rebase: {normal_cl_rebase} Gwei"})
        return Gwei(normal_cl_rebase)

    def _is_negative_specific_cl_rebase(self, ref_blockstamp: ReferenceBlockStamp) -> bool:
        """
        Calculate CL rebase from nearest and distant epochs to ref epoch given the changes in withdrawal vault
        """
        logger.info({"msg": "Calculating nearest and distant CL rebase"})
        nearest_slot = (
                ref_blockstamp.ref_slot - self.b_conf.rebase_check_nearest_epoch_distance * self.c_conf.slots_per_epoch
        )
        distant_slot = (
                ref_blockstamp.ref_slot - self.b_conf.rebase_check_distant_epoch_distance * self.c_conf.slots_per_epoch
        )

        if nearest_slot < distant_slot:
            raise ValueError(f"{nearest_slot=} should be less than {distant_slot=} in specific CL rebase calculation")
        if distant_slot < self.last_report_ref_slot:
            raise ValueError(
                f"{distant_slot=} should be greater than {self.last_report_ref_slot=} in specific CL rebase calculation"
            )

        nearest_blockstamp = get_first_non_missed_slot(
            self.w3.cc,
            SlotNumber(nearest_slot),
            last_finalized_slot_number=ref_blockstamp.slot_number,
            ref_epoch=EpochNumber(nearest_slot // self.c_conf.slots_per_epoch),
        )

        distant_blockstamp = get_first_non_missed_slot(
            self.w3.cc,
            SlotNumber(distant_slot),
            last_finalized_slot_number=ref_blockstamp.slot_number,
            ref_epoch=EpochNumber(distant_slot // self.c_conf.slots_per_epoch),
        )

        if nearest_blockstamp.block_number == distant_blockstamp.block_number:
            logger.info(
                {"msg": "Nearest and distant blocks are the same. Specific CL rebase will be calculated once"}
            )
            specific_cl_rebase = self._calculate_cl_rebase_between(nearest_blockstamp, ref_blockstamp)
            logger.info({"msg": f"Specific CL rebase: {specific_cl_rebase} Gwei"})
            return specific_cl_rebase < 0

        nearest_cl_rebase = self._calculate_cl_rebase_between(nearest_blockstamp, ref_blockstamp)
        distant_cl_rebase = self._calculate_cl_rebase_between(distant_blockstamp, ref_blockstamp)

        logger.info({"msg": f"Specific CL rebase {nearest_cl_rebase,distant_cl_rebase=} Gwei"})
        return nearest_cl_rebase < 0 or distant_cl_rebase < 0

    def _calculate_cl_rebase_between(self, prev_blockstamp: ReferenceBlockStamp, ref_blockstamp: ReferenceBlockStamp) -> Gwei:
        """
        Calculate CL rebase from prev_blockstamp to ref_blockstamp.
        Skimmed validator rewards are sent to 0x01 withdrawal credentials address
        which in Lido case is WithdrawalVault contract. To account for all changes in validators' balances,
        we must account for WithdrawalVault balance changes (withdrawn events from it)
        """
        logger.info(
            {"msg": f"Calculating CL rebase between {prev_blockstamp.ref_epoch, ref_blockstamp.ref_epoch} epochs"}
        )

        ref_lido_balance = self._calculate_real_balance(self.lido_validators)
        ref_lido_vault_balance = self._get_withdrawal_vault_balance(ref_blockstamp)
        ref_lido_balance_with_vault = ref_lido_balance + int(self.w3.from_wei(ref_lido_vault_balance, "gwei"))

        prev_all_validators = {
            v.validator.pubkey: v for v in self.w3.cc.get_validators_no_cache(prev_blockstamp)
        }
        prev_lido_validators = self.w3.lido_validators.merge_validators_with_keys(
            list(self.lido_keys.values()),
            list(prev_all_validators.values()),
        )

        prev_lido_validators_by_key = {v.validator.pubkey: v for v in prev_lido_validators}

        prev_lido_balance = self._calculate_real_balance(prev_lido_validators_by_key)
        prev_lido_vault_balance = self._get_withdrawal_vault_balance(prev_blockstamp)
        prev_lido_balance_with_vault = prev_lido_balance + int(self.w3.from_wei(prev_lido_vault_balance, "gwei"))

        # handle 32 ETH balances of freshly baked validators, who was activated between epochs
        validators_diff_in_gwei = (len(self.lido_validators) - len(prev_lido_validators_by_key)) * MAX_EFFECTIVE_BALANCE
        if validators_diff_in_gwei < 0:
            raise ValueError("Validators count diff should be positive or 0. Something went wrong with CL API")

        corrected_prev_lido_balance_with_vault = (
            prev_lido_balance_with_vault
            + validators_diff_in_gwei
            - self._get_withdrawn_from_vault_between(prev_blockstamp, ref_blockstamp)
        )

        cl_rebase = ref_lido_balance_with_vault - corrected_prev_lido_balance_with_vault

        logger.info(
            {"msg": f"CL rebase between {prev_blockstamp.ref_epoch,ref_blockstamp.ref_epoch} epochs: {cl_rebase} Gwei"}
        )

        return Gwei(cl_rebase)

    def _get_withdrawal_vault_balance(self, blockstamp: BlockStamp) -> Wei:
        withdrawal_vault_address = self.w3.lido_contracts.lido_locator.functions.withdrawalVault().call(
            block_identifier=blockstamp.block_hash
        )
        return self.w3.eth.get_balance(
            withdrawal_vault_address,
            block_identifier=blockstamp.block_hash,
        )

    def _get_withdrawn_from_vault_between(self, prev_blockstamp: ReferenceBlockStamp, curr_blockstamp: ReferenceBlockStamp) -> int:
        """
        Lookup for ETHDistributed event and sum up all withdrawalsWithdrawn
        """
        logger.info(
            {"msg": f"Get withdrawn from vault between {prev_blockstamp.ref_epoch,curr_blockstamp.ref_epoch} epochs"}
        )

        events = self._get_eth_distributed_events(
            # We added +1 to prev block number because withdrawals from vault
            # are already counted in balance state on prev block number
            from_block=BlockNumber(int(prev_blockstamp.block_number) + 1),
            to_block=BlockNumber(int(curr_blockstamp.block_number)),
        )

        if len(events) > 1:
            raise ValueError("More than one ETHDistributed event found")

        if not events:
            logger.info({"msg": "No ETHDistributed event found. Vault withdrawals: 0 Gwei."})
            return 0

        vault_withdrawals = int(self.w3.from_wei(events[0]['args']['withdrawalsWithdrawn'], 'gwei'))
        logger.info({"msg": f"Vault withdrawals: {vault_withdrawals} Gwei"})

        return vault_withdrawals

    def _get_eth_distributed_events(self, from_block: BlockNumber, to_block: BlockNumber) -> list[EventData]:
        return self.w3.lido_contracts.lido.events.ETHDistributed.get_logs(
            fromBlock=from_block,
            toBlock=to_block,
        )

    @staticmethod
    def _calculate_real_balance(validators: Mapping[Any, Validator]) -> Gwei:
        return Gwei(sum(int(v.balance) for v in validators.values()))

    def _calculate_normal_cl_rebase(
        self, epochs_passed: int, mean_total_lido_effective_balance: int, mean_total_effective_balance: int
    ) -> Gwei:
        """
        Calculate normal CL rebase for particular effective balance

        Actual value of NORMALIZED_CL_PER_EPOCH is a random variable with embedded variance for four reasons:
         * Calculating expected proposer rewards instead of actual - Randomness within specification
         * Calculating expected sync committee rewards instead of actual  - Randomness within specification
         * Instead of using data on active validators for each epoch
          estimation on number of active validators through interception of
          active validators between current oracle report epoch and last one - Randomness within measurement algorithm
         * Not absolutely ideal performance of Lido Validators and network as a whole  - Randomness of real world
        If the difference between observed real CL rewards and its theoretical normalized couldn't be explained by
        those 4 factors that means there is an additional factor leading to lower rewards - incidents within Protocol.
        To formalize “high enough” difference we’re suggesting NORMALIZED_CL_MISTAKE_PERCENT constant
        """
        normal_cl_rebase = int(
            (self.b_conf.normalized_cl_reward_per_epoch * mean_total_lido_effective_balance * epochs_passed)
            / math.sqrt(mean_total_effective_balance) * (1 - self.b_conf.normalized_cl_reward_mistake_rate)
        )
        return Gwei(normal_cl_rebase)
