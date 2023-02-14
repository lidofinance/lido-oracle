import math
import logging
from collections import defaultdict

from src.providers.keys.typings import LidoKey
from src.utils.helpers import get_first_non_missed_slot
from src.web3_extentions import LidoValidator
from src.web3_extentions.typings import Web3

from src.modules.accounting.typings import Gwei
from src.modules.submodules.consensus import FrameConfig, ChainConfig, MemberInfo
from src.providers.consensus.typings import ValidatorStatus, Validator
from src.typings import BlockStamp, SlotNumber, EpochNumber

# Constants from consensus spec
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 256
EPOCHS_PER_SLASHINGS_VECTOR = 8192
PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3
EFFECTIVE_BALANCE_INCREMENT = 2 ** 0 * 10 ** 9
MIN_DEPOSIT_AMOUNT = 32 * 10 ** 9

FIRST_DEPOSIT_EVENT_LOOKUP_MAXIMUM_BLOCKS_DISTANCE = 225 * 7

NORMALIZED_CL_PER_EPOCH = 56  # todo: look at this with analytics team, they suggest 57
MISTAKE_RANGE = 0.1
NEAREST_EPOCH_DISTANCE = 4
FAR_EPOCH_DISTANCE = 25

logger = logging.getLogger(__name__)


class BunkerService:

    def __init__(
        self,
        w3: Web3,
        member_info: MemberInfo,
        frame_config: FrameConfig,
        chain_config: ChainConfig
    ):
        self.w3 = w3
        self.m_info = member_info
        self.f_conf = frame_config
        self.c_conf = chain_config
        # Will be filled in `is_bunker_mode` call
        self.all_validators: list[Validator] = []
        self.lido_keys: list[LidoKey] = []
        self.lido_validators: list[LidoValidator] = []

    def is_bunker_mode(self, blockstamp: BlockStamp) -> bool:
        self.all_validators, self.lido_keys, self.lido_validators = self._get_lido_validators_with_others(blockstamp)
        logger.info({"msg": f"Validators - all: {len(self.all_validators)} lido: {len(self.lido_validators)}"})
        logger.info({"msg": "Checking bunker mode"})
        frame_cl_rebase = self._get_cl_rebase_for_frame(blockstamp)
        if frame_cl_rebase < 0:
            logger.info({"msg": "Bunker ON. CL rebase is negative"})
            return True
        if self._is_high_midterm_slashing_penalty(blockstamp, frame_cl_rebase):
            logger.info({"msg": "Bunker ON. High midterm slashing penalty"})
            return True
        if self._is_abnormal_cl_rebase(blockstamp, frame_cl_rebase):
            logger.info({"msg": "Bunker ON. Abnormal CL rebase"})
            return True

    def _get_cl_rebase_for_frame(self, blockstamp: BlockStamp) -> Gwei:
        logger.info({"msg": "Getting CL rebase for frame"})
        ref_lido_balance, ref_withdrawal_vault_balance = self._calculate_lido_balance_with_vault(
            self.lido_validators, blockstamp
        )
        # Make a static call of 'handleOracleReport' without EL rewards
        # to simulate report and get total pool ether after that
        args = {
            "_reportTimestamp": blockstamp.slot_number * self.c_conf.seconds_per_slot + self.c_conf.genesis_time,
            "_timeElapsed": (blockstamp.slot_number - self.m_info.last_member_report_ref_slot) * self.c_conf.seconds_per_slot,
            "_clValidators": len(self.lido_validators),
            "_clBalance": self.w3.to_wei(ref_lido_balance, 'gwei'),
            "_withdrawalVaultBalance": ref_withdrawal_vault_balance,
            "_elRewardsVaultBalance": 0,
            "_lastFinalizableRequestId": 0,
            "_simulatedShareRate": 0,
        }
        before_report_total_pooled_ether = self.w3.lido_contracts.lido.functions.totalSupply().call(
            block_identifier=blockstamp.block_hash
        )
        after_report_total_pooled_ether, _ = self.w3.lido_contracts.lido.functions.handleOracleReport(**args).call(
            block_identifier=blockstamp.block_hash
        )
        logger.info({
            "msg": "Simulate 'handleOracleReport' contract function call",
            "call_args": args,
            "before_call": before_report_total_pooled_ether,
            "after_call": after_report_total_pooled_ether,
        })

        frame_cl_rebase = self.w3.from_wei(after_report_total_pooled_ether - before_report_total_pooled_ether, 'gwei')
        logger.info({"msg": f"Simulated CL rebase for frame: {frame_cl_rebase} Gwei"})

        return Gwei(frame_cl_rebase)

    def _is_high_midterm_slashing_penalty(self, blockstamp: BlockStamp, cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Detecting high midterm slashing penalty"})
        ref_epoch = EpochNumber(blockstamp.slot_number // self.c_conf.slots_per_epoch)
        all_slashed_validators = self._not_withdrawn_slashed_validators(self.all_validators, ref_epoch)
        lido_slashed_validators: list[Validator] = [
            v.validator for v in self.w3.lido_validators.filter_lido_validators(self.lido_keys, all_slashed_validators)
        ]
        logger.info({"msg": f"Slashed: {len(all_slashed_validators)=} | {len(lido_slashed_validators)=}"})

        # If no one lido in current slashed validators - no need to bunker
        if not lido_slashed_validators:
            return False

        # We should calculate total_balance for each bucket, but we do it once for all per_epoch_buckets
        total_balance = self._calculate_total_effective_balance(self.all_validators)
        # Calculate lido midterm penalties in each epoch where lido slashed
        per_epoch_buckets = self._get_per_epoch_buckets(lido_slashed_validators, ref_epoch)
        per_epoch_lido_midterm_penalties = self._get_per_epoch_lido_midterm_penalties(
            per_epoch_buckets, lido_slashed_validators, total_balance
        )
        # Calculate lido midterm penalties impact in each frame
        per_frame_buckets = self._get_per_frame_lido_midterm_penalties(per_epoch_lido_midterm_penalties, self.f_conf)

        # If any midterm penalty sum of lido validators in frame bucket greater than rebase we should trigger bunker
        max_lido_midterm_penalty = max(per_frame_buckets.values())
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})
        if max_lido_midterm_penalty > cl_rebase:
            return True

        return False

    def _is_abnormal_cl_rebase(self, blockstamp: BlockStamp, frame_cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Checking abnormal CL rebase"})
        normal_cl_rebase = self._calculate_normal_cl_rebase(blockstamp)
        if frame_cl_rebase < normal_cl_rebase:
            logger.info({"msg": "Abnormal CL rebase in frame"})
            nearest_cl_rebase, far_cl_rebase = self._calculate_nearest_and_far_cl_rebase(blockstamp)
            if nearest_cl_rebase < 0 or far_cl_rebase < 0:
                return True
        return False

    def _calculate_normal_cl_rebase(self, blockstamp: BlockStamp) -> Gwei:
        """
        Calculate normal CL rebase (relative to all validators and the previous Lido frame)
        for current frame for Lido validators
        """
        current_ref_epoch = EpochNumber(blockstamp.slot_number // self.c_conf.slots_per_epoch)
        last_report_blockstamp = get_first_non_missed_slot(
            self.w3.cc, self.m_info.last_member_report_ref_slot, self.c_conf.slots_per_epoch * self.f_conf.epochs_per_frame
        )
        last_member_report_ref_epoch = EpochNumber(last_report_blockstamp.slot_number // self.c_conf.slots_per_epoch)

        total_ref_effective_balance = self._calculate_total_effective_balance(self.all_validators)
        total_ref_lido_effective_balance = self._calculate_total_effective_balance(
            [v.validator for v in self.lido_validators]
        )

        if last_member_report_ref_epoch <= self.f_conf.initial_epoch:
            # If no one report was made - we should use initial epoch as last completed epoch
            # Because in this case 'cl_rebase' will contain all rewards from initial epoch
            last_completed_epoch = self.f_conf.initial_epoch
            total_last_effective_balance = total_ref_effective_balance
            total_last_lido_effective_balance = total_ref_lido_effective_balance
        else:
            last_completed_epoch = last_member_report_ref_epoch
            last_all_validators = self.w3.cc.get_validators(last_report_blockstamp.state_root)
            last_lido_validators = self.w3.lido_validators.filter_lido_validators(self.lido_keys, last_all_validators)
            total_last_effective_balance = self._calculate_total_effective_balance(last_all_validators)
            total_last_lido_effective_balance = self._calculate_total_effective_balance(
                [v.validator for v in last_lido_validators]
            )

        mean_total_effective_balance = (total_ref_effective_balance + total_last_effective_balance) // 2
        mean_total_lido_effective_balance = (
            (total_ref_lido_effective_balance + total_last_lido_effective_balance) // 2
        )

        epochs_passed = current_ref_epoch - last_completed_epoch

        normal_cl_rebase = self._get_normal_cl_rebase(
            epochs_passed, mean_total_lido_effective_balance, mean_total_effective_balance
        )

        logger.info({"msg": f"Normal CL rebase: {normal_cl_rebase} Gwei"})
        return Gwei(normal_cl_rebase)

    def _calculate_nearest_and_far_cl_rebase(self, blockstamp: BlockStamp) -> tuple[Gwei, Gwei]:
        """
        Calculate CL rebase from nearest and far epochs to ref epoch given the changes in withdrawal vault
        """
        logger.info({"msg": "Calculating nearest and far CL rebase"})
        nearest_slot = (blockstamp.slot_number - NEAREST_EPOCH_DISTANCE * self.c_conf.slots_per_epoch)
        far_slot = (blockstamp.slot_number - FAR_EPOCH_DISTANCE * self.c_conf.slots_per_epoch)
        lookup_max_deep = self.c_conf.slots_per_epoch * self.f_conf.epochs_per_frame
        nearest_blockstamp = get_first_non_missed_slot(self.w3.cc, SlotNumber(nearest_slot), lookup_max_deep)
        far_blockstamp = get_first_non_missed_slot(self.w3.cc, SlotNumber(far_slot), lookup_max_deep)
        nearest_cl_rebase = self._calculate_cl_rebase_from(blockstamp, nearest_blockstamp)
        far_cl_rebase = self._calculate_cl_rebase_from(blockstamp, far_blockstamp)

        logger.info({"msg": f"CL rebase {nearest_cl_rebase,far_cl_rebase=}"})
        return nearest_cl_rebase, far_cl_rebase

    def _calculate_cl_rebase_from(self, curr_ref_blockstamp: BlockStamp, prev_blockstamp: BlockStamp) -> Gwei:
        """
        Calculate CL rebase from prev_blockstamp to ref_blockstamp given the changes in withdrawal vault
        """
        curr_ref_epoch = curr_ref_blockstamp.slot_number // self.c_conf.slots_per_epoch
        prev_epoch = prev_blockstamp.slot_number // self.c_conf.slots_per_epoch
        logger.info({"msg": f"Calculating CL rebase between {prev_epoch, curr_ref_epoch=}"})

        ref_lido_balance_with_vault = sum(self._calculate_lido_balance_with_vault(
            self.lido_validators, curr_ref_blockstamp
        ))

        prev_all_validators = self.w3.cc.get_validators(prev_blockstamp.state_root)
        prev_lido_validators = self.w3.lido_validators.filter_lido_validators(self.lido_keys, prev_all_validators)
        prev_lido_balance_with_vault = sum(self._calculate_lido_balance_with_vault(
            prev_lido_validators, prev_blockstamp
        ))

        # handle 32 ETH balances of freshly baked validators, who was activated between epochs
        validators_diff_in_gwei = (len(self.lido_validators) - len(prev_lido_validators)) * MIN_DEPOSIT_AMOUNT
        assert validators_diff_in_gwei >= 0, "Validators diff should be positive or 0. Something went wrong with CL API"

        corrected_prev_lido_balance_with_vault = (
            prev_lido_balance_with_vault
            + validators_diff_in_gwei
            - self._get_withdrawn_from_vault_between(prev_blockstamp, curr_ref_blockstamp)
        )

        cl_rebase = ref_lido_balance_with_vault - corrected_prev_lido_balance_with_vault

        logger.info({"msg": f"CL rebase from {prev_epoch=}: {cl_rebase} Gwei"})

        return cl_rebase

    def _calculate_lido_balance_with_vault(
        self, lido_validators: list[LidoValidator], vault_balance_at_blockstamp: BlockStamp
    ) -> tuple[Gwei, Gwei]:
        """
        Calculate Lido validators balance and balance in withdrawal vault contract in particular block
        """
        lido_balance = sum(int(v.validator.balance) for v in lido_validators)
        withdrawal_vault_balance = self.w3.eth.get_balance(
            self.w3.lido_contracts.withdrawal_vault.address, vault_balance_at_blockstamp.block_hash
        )

        return Gwei(lido_balance), Gwei(self.w3.from_wei(withdrawal_vault_balance, 'gwei'))

    def _get_withdrawn_from_vault_between(self, prev_blockstamp: BlockStamp, curr_blockstamp: BlockStamp) -> int:
        """
        Lookup for ETHDistributed event and sum up all withdrawalsWithdrawn
        """
        prev_epoch = prev_blockstamp.slot_number // self.c_conf.slots_per_epoch
        curr_epoch = curr_blockstamp.slot_number // self.c_conf.slots_per_epoch
        logger.info({"msg": f"Get withdrawn from vault between {prev_epoch,curr_epoch=}"})
        vault_withdrawals = 0
        events = self.w3.lido_contracts.lido.events.ETHDistributed.get_logs(
            from_block=int(prev_blockstamp.block_number) + 1, to_block=int(curr_blockstamp.block_number)
        )
        for event in events:
            vault_withdrawals += event['args']['withdrawalsWithdrawn']

        vault_withdrawals = self.w3.from_wei(vault_withdrawals, 'gwei')

        logger.info({"msg": f"Vault withdrawals: {vault_withdrawals} Gwei"})

        return vault_withdrawals

    def _get_lido_validators_with_others(
        self, blockstamp: BlockStamp
    ) -> tuple[list[Validator], list[LidoKey], list[LidoValidator]]:
        lido_keys = self.w3.kac.get_all_lido_keys(blockstamp)
        validators = self.w3.cc.get_validators(blockstamp.state_root)
        lido_validators = self.w3.lido_validators.filter_lido_validators(lido_keys, validators)

        return validators, lido_keys, lido_validators

    @staticmethod
    def _calculate_total_effective_balance(all_validators: list[Validator]) -> Gwei:
        """
        Calculates total balance of all active validators in network
        """
        total_effective_balance = 0

        for v in all_validators:
            if v.status in [
                ValidatorStatus.ACTIVE_ONGOING,
                ValidatorStatus.ACTIVE_EXITING,
                ValidatorStatus.ACTIVE_SLASHED
            ]:
                total_effective_balance += int(v.validator.effective_balance)

        return Gwei(total_effective_balance)

    @staticmethod
    def _not_withdrawn_slashed_validators(all_validators: list[Validator], ref_epoch: EpochNumber) -> list[Validator]:
        """
        Get all slashed validators, who are not withdrawn yet
        """
        slashed_validators = []

        for validator in all_validators:
            v = validator.validator
            if v.slashed and int(v.withdrawable_epoch) > ref_epoch:
                slashed_validators.append(validator)

        return slashed_validators

    @staticmethod
    def _get_per_epoch_buckets(
        all_slashed_validators: list[Validator], ref_epoch: EpochNumber
    ) -> dict[EpochNumber, list[Validator]]:
        """
        Fill per_epoch_buckets by possible slashed epochs
        It detects slashing epoch range for validator
        If difference between validator's withdrawable epoch and exit epoch is greater enough,
        then we can be sure that validator was slashed in particular epoch
        Otherwise, we can only assume that validator was slashed in epochs range
        due because its exit epoch shifted because of huge exit queue
        Read more here: https://hackmd.io/@lido/r1Qkkiv3j
        """
        per_epoch_buckets = defaultdict(list[Validator])
        for validator in all_slashed_validators:
            v = validator.validator
            if not v.slashed:
                raise Exception("Validator should be slashed to detect slashing epoch range")
            possible_slashed_epoch = int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR
            if int(v.withdrawable_epoch) - int(v.exit_epoch) > MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
                per_epoch_buckets[possible_slashed_epoch].append(validator)
                continue
            else:
                for epoch in range(possible_slashed_epoch, ref_epoch + 1):
                    per_epoch_buckets[epoch].append(validator)

        return per_epoch_buckets

    @staticmethod
    def _get_per_epoch_lido_midterm_penalties(
        per_epoch_buckets: dict[EpochNumber, list[Validator]],
        lido_slashed_validators: list[Validator],
        total_balance: Gwei,
    ) -> dict[EpochNumber, Gwei]:
        """
        Iterate through per_epoch_buckets and calculate lido midterm penalties for each bucket
        """
        min_bucket_epoch = min(per_epoch_buckets.keys())
        per_epoch_lido_midterm_penalties: dict[EpochNumber, Gwei] = defaultdict(int)
        for epoch, slashed_validators in per_epoch_buckets.items():
            slashed_keys = set(k.validator.pubkey for k in slashed_validators)
            lido_validators_slashed_in_epoch = [
                v for v in lido_slashed_validators if v.validator.pubkey in slashed_keys
            ]
            if not lido_validators_slashed_in_epoch:
                continue
            # We should calculate penalties according to bounded slashings in past EPOCHS_PER_SLASHINGS_VECTOR
            min_bounded_epoch = max(min_bucket_epoch, EpochNumber(epoch - EPOCHS_PER_SLASHINGS_VECTOR))
            bounded_slashings_balance_sum = sum([
                sum(int(v.validator.effective_balance) for v in e_vals)
                for e, e_vals in per_epoch_buckets.items() if min_bounded_epoch <= e <= epoch
            ])  # aka state.slashings from spec
            adjusted_total_slashing_balance = min(
                bounded_slashings_balance_sum * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
                total_balance
            )
            for v in lido_validators_slashed_in_epoch:
                effective_balance = int(v.validator.effective_balance)
                penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
                penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT
                per_epoch_lido_midterm_penalties[epoch] += penalty
        return per_epoch_lido_midterm_penalties

    @staticmethod
    def _get_per_frame_lido_midterm_penalties(
        per_epoch_lido_midterm_penalties: dict[EpochNumber, Gwei],
        frame_config: FrameConfig,
    ) -> dict[int, Gwei]:
        """
        Put per epoch buckets into per frame buckets to calculate lido midterm penalties impact in each frame
        """
        min_lido_midterm_penalty_epoch = min(per_epoch_lido_midterm_penalties.keys())
        per_frame_buckets: dict[int, Gwei] = defaultdict(int)
        left_border = min_lido_midterm_penalty_epoch
        right_border = frame_config.initial_epoch + frame_config.epochs_per_frame
        # The first bucket should have flexible size
        while right_border <= min_lido_midterm_penalty_epoch:
            right_border += frame_config.epochs_per_frame
        index = 0
        for epoch, midterm_penalty_sum in sorted(per_epoch_lido_midterm_penalties.items()):
            if epoch > right_border:
                index += 1
                left_border = right_border + 1
                right_border += frame_config.epochs_per_frame
            if left_border <= epoch <= right_border:
                per_frame_buckets[index] += midterm_penalty_sum
        return per_frame_buckets

    @staticmethod
    def _get_normal_cl_rebase(
        epochs_passed: int, mean_total_lido_effective_balance: int, mean_total_effective_balance: int
    ) -> Gwei:
        normal_cl_rebase = int(
            (NORMALIZED_CL_PER_EPOCH * mean_total_lido_effective_balance * epochs_passed)
            / (math.sqrt(mean_total_effective_balance) * (1 - MISTAKE_RANGE))
        )
        return Gwei(normal_cl_rebase)
