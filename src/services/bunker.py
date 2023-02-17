import math
import logging
from collections import defaultdict
from functools import lru_cache

from src.providers.keys.typings import LidoKey
from src.utils.helpers import get_first_non_missed_slot
from src.web3_extentions import LidoValidator
from src.web3_extentions.typings import Web3

from src.modules.accounting.typings import Gwei, wei
from src.modules.submodules.consensus import FrameConfig, ChainConfig
from src.providers.consensus.typings import Validator
from src.typings import BlockStamp, SlotNumber, EpochNumber

# Constants from consensus spec
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 256
EPOCHS_PER_SLASHINGS_VECTOR = 8192
PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3
EFFECTIVE_BALANCE_INCREMENT = 2 ** 0 * 10 ** 9
MIN_DEPOSIT_AMOUNT = 32 * 10 ** 9

# todo: should be in contract
NORMALIZED_CL_PER_EPOCH = 64  # equal BASE_REWARD_FACTOR from consensus spec
# But actual value of NORMALIZED_CL_PER_EPOCH is a random variable with embedded variance for four reasons:
#  * Calculating expected proposer rewards instead of actual - Randomness within specification
#  * Calculating expected sync committee rewards instead of actual  - Randomness within specification
#  * Instead of using data on active validators for each epoch
#    estimation on number of active validators through interception of
#    active validators between current oracle report epoch and last one - Randomness within measurement algorithm
#  * Not absolutely ideal performance of Lido Validators and network as a whole  - Randomness of real world
# If the difference between observed real CL rewards and its theoretical normalized couldn't be explained by
# those 4 factors that means there is an additional factor leading to lower rewards - incidents within Protocol.
# To formalize “high enough” difference we’re suggesting NORMALIZED_CL_MISTAKE_PERCENT constant
NORMALIZED_CL_MISTAKE_PERCENT = 10
NEAREST_EPOCH_DISTANCE = 4
FAR_EPOCH_DISTANCE = 25

logger = logging.getLogger(__name__)


class BunkerService:

    def __init__(
        self,
        w3: Web3,
        frame_config: FrameConfig,
        chain_config: ChainConfig
    ):
        self.w3 = w3
        self.f_conf = frame_config
        self.c_conf = chain_config
        # Will be filled in `is_bunker_mode` call
        self.last_report_ref_slot = SlotNumber(0)
        self.all_validators: dict[str, Validator] = {}
        self.lido_keys: dict[str, LidoKey] = {}
        self.lido_validators: dict[str, LidoValidator] = {}

    def is_bunker_mode(self, blockstamp: BlockStamp) -> bool:
        self.last_report_ref_slot = self.w3.lido_contracts.accounting_oracle.functions.getLastProcessingRefSlot().call(
            block_identifier=blockstamp.block_hash
        )
        if self.last_report_ref_slot == 0:
            logger.info({"msg": "No one report yet. Bunker status will not be checked"})
            return False

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

        return False

    def _get_cl_rebase_for_frame(self, blockstamp: BlockStamp) -> Gwei:
        logger.info({"msg": "Getting CL rebase for frame"})
        ref_lido_balance = self._calculate_real_balance(self.lido_validators)
        ref_withdrawal_vault_balance = self._get_withdrawal_vault_balance(blockstamp)
        # Make a static call of 'handleOracleReport' without EL rewards
        # to simulate report and get total pool ether after that
        args = {
            "_reportTimestamp": blockstamp.ref_slot_number * self.c_conf.seconds_per_slot + self.c_conf.genesis_time,
            "_timeElapsed": (blockstamp.ref_slot_number - self.last_report_ref_slot) * self.c_conf.seconds_per_slot,
            "_clValidators": len(self.lido_validators),
            "_clBalance": ref_lido_balance,
            "_withdrawalVaultBalance": ref_withdrawal_vault_balance,
            "_elRewardsVaultBalance": 0,
            "_lastFinalizableRequestId": 0,
            "_simulatedShareRate": 0,
        }
        before_report_total_pooled_ether = self.w3.lido_contracts.lido.functions.totalSupply().call(
            block_identifier=blockstamp.block_hash
        )
        after_report_total_pooled_ether, *_ = self.w3.lido_contracts.lido.functions.handleOracleReport(**args).call(
            {'from': self.w3.lido_contracts.accounting_oracle.address},
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
        all_slashed_validators = self._not_withdrawn_slashed_validators(self.all_validators, blockstamp.ref_epoch)
        lido_slashed_validators: dict[str, LidoValidator] = self.w3.lido_validators.filter_lido_validators_dict(
            self.lido_keys, all_slashed_validators
        )
        logger.info({"msg": f"Slashed: {len(all_slashed_validators)=} | {len(lido_slashed_validators)=}"})

        # If no one Lido in current slashed validators - no need to bunker
        if not lido_slashed_validators:
            return False

        # We should calculate total_balance for each bucket, but we do it once for all per_epoch_buckets
        total_balance = self._calculate_total_active_effective_balance(self.all_validators, blockstamp.ref_epoch)
        # Calculate lido midterm penalties in each epoch where lido slashed
        per_epoch_buckets = self._get_per_epoch_buckets(lido_slashed_validators, blockstamp.ref_epoch)
        per_epoch_lido_midterm_penalties = self._get_per_epoch_lido_midterm_penalties(
            per_epoch_buckets, lido_slashed_validators, total_balance
        )
        # Calculate lido midterm penalties impact in each frame
        per_frame_buckets = self._get_per_frame_lido_midterm_penalties(per_epoch_lido_midterm_penalties, self.f_conf)

        # If any midterm penalty sum of lido validators in frame bucket greater than rebase we should trigger bunker
        max_lido_midterm_penalty = max(per_frame_buckets)
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})
        # Compare with current CL rebase, because we can't predict how much CL rebase will be in the next frames
        # and whether they will cover future midterm penalties, so that the bunker is better to be turned on than not
        if max_lido_midterm_penalty > cl_rebase:
            return True

        return False

    def _is_abnormal_cl_rebase(self, blockstamp: BlockStamp, frame_cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Checking abnormal CL rebase"})
        normal_cl_rebase = self._get_normal_cl_rebase(blockstamp)
        if frame_cl_rebase < normal_cl_rebase:
            logger.info({"msg": "Abnormal CL rebase in frame"})
            if NEAREST_EPOCH_DISTANCE == 0 and FAR_EPOCH_DISTANCE == 0:
                logger.info({"msg": "Specific CL rebase calculation are disabled"})
                return True
            is_negative_specific_cl_rebase = self._is_negative_specific_cl_rebase(blockstamp)
            if is_negative_specific_cl_rebase:
                return True
        return False

    def _get_normal_cl_rebase(self, blockstamp: BlockStamp) -> Gwei:
        """
        Calculate normal CL rebase (relative to all validators and the previous Lido frame)
        for current frame for Lido validators
        """
        last_report_blockstamp = get_first_non_missed_slot(
            self.w3.cc, self.last_report_ref_slot, self.c_conf.slots_per_epoch * self.f_conf.epochs_per_frame
        )

        total_ref_effective_balance = self._calculate_total_active_effective_balance(
            self.all_validators, blockstamp.ref_epoch)
        total_ref_lido_effective_balance = self._calculate_total_active_effective_balance(
            self.lido_validators, blockstamp.ref_epoch
        )

        last_all_validators = {
            v.validator.pubkey: v for v in self.w3.cc.get_validators(last_report_blockstamp.state_root)
        }
        last_lido_validators = self.w3.lido_validators.filter_lido_validators_dict(
            self.lido_keys, last_all_validators
        )
        total_last_effective_balance = self._calculate_total_active_effective_balance(
            last_all_validators, last_report_blockstamp.ref_epoch
        )
        total_last_lido_effective_balance = self._calculate_total_active_effective_balance(
            last_lido_validators, last_report_blockstamp.ref_epoch
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

    def _is_negative_specific_cl_rebase(self, blockstamp: BlockStamp) -> bool:
        """
        Calculate CL rebase from nearest and far epochs to ref epoch given the changes in withdrawal vault
        """
        logger.info({"msg": "Calculating nearest and far CL rebase"})
        nearest_slot = (blockstamp.ref_slot_number - NEAREST_EPOCH_DISTANCE * self.c_conf.slots_per_epoch)
        far_slot = (blockstamp.ref_slot_number - FAR_EPOCH_DISTANCE * self.c_conf.slots_per_epoch)

        if nearest_slot < far_slot:
            raise ValueError(f"{nearest_slot=} should be less than {far_slot=} in specific CL rebase calculation")
        if far_slot < self.last_report_ref_slot:
            raise ValueError(
                f"{far_slot=} should be greater than {self.last_report_ref_slot=} in specific CL rebase calculation"
            )

        lookup_max_deep = self.c_conf.slots_per_epoch * self.f_conf.epochs_per_frame
        nearest_blockstamp = get_first_non_missed_slot(self.w3.cc, SlotNumber(nearest_slot), lookup_max_deep)
        far_blockstamp = get_first_non_missed_slot(self.w3.cc, SlotNumber(far_slot), lookup_max_deep)

        nearest_cl_rebase = self._calculate_cl_rebase_between(nearest_blockstamp, blockstamp)
        far_cl_rebase = self._calculate_cl_rebase_between(far_blockstamp, blockstamp)

        logger.info({"msg": f"CL rebase {nearest_cl_rebase,far_cl_rebase=}"})
        return nearest_cl_rebase < 0 or far_cl_rebase < 0

    @lru_cache(maxsize=1)
    def _calculate_cl_rebase_between(self, prev_blockstamp: BlockStamp, curr_blockstamp: BlockStamp) -> Gwei:
        """
        Calculate CL rebase from prev_blockstamp to ref_blockstamp.
        Skimmed validator rewards are sent to 0x01 withdrawal credentials address
        which in Lido case is WithdrawalVault contract. To account for all changes in validators' balances,
        we must account for WithdrawalVault balance changes (withdrawn events from it)
        """
        logger.info(
            {"msg": f"Calculating CL rebase between {prev_blockstamp.ref_epoch, curr_blockstamp.ref_epoch} epochs"}
        )

        ref_lido_balance = self._calculate_real_balance(self.lido_validators)
        ref_lido_vault_balance = self._get_withdrawal_vault_balance(curr_blockstamp)
        ref_lido_balance_with_vault = ref_lido_balance + self.w3.from_wei(ref_lido_vault_balance, "gwei")

        prev_all_validators = {
            v.validator.pubkey: v for v in self.w3.cc.get_validators(prev_blockstamp.state_root)
        }
        prev_lido_validators = self.w3.lido_validators.filter_lido_validators_dict(self.lido_keys, prev_all_validators)
        prev_lido_balance = self._calculate_real_balance(prev_lido_validators)
        prev_lido_vault_balance = self._get_withdrawal_vault_balance(prev_blockstamp)
        prev_lido_balance_with_vault = prev_lido_balance + self.w3.from_wei(prev_lido_vault_balance, "gwei")

        # handle 32 ETH balances of freshly baked validators, who was activated between epochs
        validators_diff_in_gwei = (len(self.lido_validators) - len(prev_lido_validators)) * MIN_DEPOSIT_AMOUNT
        if validators_diff_in_gwei < 0:
            raise Exception("Validators diff should be positive or 0. Something went wrong with CL API")

        corrected_prev_lido_balance_with_vault = (
            prev_lido_balance_with_vault
            + validators_diff_in_gwei
            - self._get_withdrawn_from_vault_between(prev_blockstamp, curr_blockstamp)
        )

        cl_rebase = ref_lido_balance_with_vault - corrected_prev_lido_balance_with_vault

        logger.info(
            {"msg": f"CL rebase between {prev_blockstamp.ref_epoch,curr_blockstamp.ref_epoch} epochs: {cl_rebase} Gwei"}
        )

        return cl_rebase

    def _get_withdrawal_vault_balance(self, blockstamp: BlockStamp) -> wei:
        withdrawal_vault_address = self.w3.lido_contracts.lido_locator.functions.withdrawalVault().call(
            block_identifier=blockstamp.block_hash
        )
        return self.w3.eth.get_balance(
            withdrawal_vault_address, blockstamp.block_hash
        )

    def _get_withdrawn_from_vault_between(self, prev_blockstamp: BlockStamp, curr_blockstamp: BlockStamp) -> int:
        """
        Lookup for ETHDistributed event and sum up all withdrawalsWithdrawn
        """
        logger.info(
            {"msg": f"Get withdrawn from vault between {prev_blockstamp.ref_epoch,curr_blockstamp.ref_epoch} epochs"}
        )
        events = self.w3.lido_contracts.lido.events.ETHDistributed.get_logs(
            # We added +1 to prev block number because withdrawals from vault
            # are already counted in balance state on prev block number
            from_block=int(prev_blockstamp.block_number) + 1, to_block=int(curr_blockstamp.block_number)
        )

        if len(events) > 1:
            raise Exception(f"More than one ETHDistributed event found")

        vault_withdrawals = self.w3.from_wei(events[0]['args']['withdrawalsWithdrawn'], 'gwei')
        logger.info({"msg": f"Vault withdrawals: {vault_withdrawals} Gwei"})

        return vault_withdrawals

    def _get_lido_validators_with_others(
        self, blockstamp: BlockStamp
    ) -> tuple[dict[str, Validator], dict[str, LidoKey], dict[str, LidoValidator]]:
        lido_keys = {k.key: k for k in self.w3.kac.get_all_lido_keys(blockstamp)}
        validators = {v.validator.pubkey: v for v in self.w3.cc.get_validators(blockstamp.state_root)}
        lido_validators = self.w3.lido_validators.filter_lido_validators_dict(lido_keys, validators)

        return validators, lido_keys, lido_validators

    @staticmethod
    def _calculate_real_balance(validators: dict[str, Validator]) -> Gwei:
        return Gwei(sum(int(v.balance) for v in validators.values()))

    @staticmethod
    def _calculate_total_active_effective_balance(validators: dict[str, Validator], ref_epoch: EpochNumber) -> Gwei:
        """
        Calculates total balance of all active validators in network
        """
        total_effective_balance = 0

        for v in validators.values():
            if int(v.validator.activation_epoch) <= ref_epoch < int(v.validator.exit_epoch):
                total_effective_balance += int(v.validator.effective_balance)

        return Gwei(total_effective_balance)

    @staticmethod
    def _not_withdrawn_slashed_validators(
        all_validators: dict[str, Validator], ref_epoch: EpochNumber
    ) -> dict[str, Validator]:
        """
        Get all slashed validators, who are not withdrawn yet
        """
        slashed_validators: dict[str, Validator] = defaultdict(Validator)

        for key, v in all_validators.items():
            if v.validator.slashed and int(v.validator.withdrawable_epoch) > ref_epoch:
                slashed_validators[key] = v

        return slashed_validators

    @staticmethod
    def _get_per_epoch_buckets(
        all_slashed_validators: dict[str, Validator], ref_epoch: EpochNumber
    ) -> dict[EpochNumber, dict[str, Validator]]:
        """
        Fill per_epoch_buckets by possible slashed epochs
        It detects slashing epoch range for validator
        If difference between validator's withdrawable epoch and exit epoch is greater enough,
        then we can be sure that validator was slashed in particular epoch
        Otherwise, we can only assume that validator was slashed in epochs range
        due because its exit epoch shifted because of huge exit queue

        Read more here:
        https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/beacon-chain.md#modified-slash_validator
        https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#initiate_validator_exit
        """
        per_epoch_buckets = defaultdict(dict[str, Validator])
        for key, validator in all_slashed_validators.items():
            v = validator.validator
            if not v.slashed:
                raise Exception("Validator should be slashed to detect slashing epoch range")
            if int(v.withdrawable_epoch) - int(v.exit_epoch) > MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
                determined_slashed_epoch = int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR
                per_epoch_buckets[determined_slashed_epoch][key] = validator
                continue
            else:
                possible_slashed_epoch = int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR
                for epoch in range(ref_epoch - EPOCHS_PER_SLASHINGS_VECTOR, possible_slashed_epoch + 1):
                    per_epoch_buckets[epoch][key] = validator

        return per_epoch_buckets

    def _get_per_epoch_lido_midterm_penalties(
        self,
        per_epoch_buckets: dict[EpochNumber, dict[str, Validator]],
        lido_slashed_validators: dict[str, Validator],
        total_balance: Gwei,
    ) -> dict[EpochNumber, dict[str, Gwei]]:
        """
        Iterate through per_epoch_buckets and calculate lido midterm penalties for each bucket
        """
        per_epoch_lido_midterm_penalties: dict[EpochNumber, dict[str, Gwei]] = defaultdict(dict)
        for epoch, slashed_validators in per_epoch_buckets.items():
            lido_validators_slashed_in_epoch: dict[str, LidoValidator] = {
                key: slashed_validators[key] for key in lido_slashed_validators if key in slashed_validators
            }
            if not lido_validators_slashed_in_epoch:
                continue
            # We should calculate penalties according to bounded slashings in past EPOCHS_PER_SLASHINGS_VECTOR
            bounded_slashed_validators = self._get_bounded_slashed_validators(per_epoch_buckets, epoch)
            slashings = sum(int(v.validator.effective_balance) for v in bounded_slashed_validators.values())
            adjusted_total_slashing_balance = min(
                slashings * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
                total_balance
            )
            for key, v in lido_validators_slashed_in_epoch.items():
                effective_balance = int(v.validator.effective_balance)
                penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
                penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT
                midterm_penalty_epoch = EpochNumber(
                    int(v.validator.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR // 2
                )
                per_epoch_lido_midterm_penalties[midterm_penalty_epoch][key] = penalty
        return per_epoch_lido_midterm_penalties

    @staticmethod
    def _get_bounded_slashed_validators(
        per_epoch_buckets: dict[EpochNumber, dict[str, Validator]],
        bound_with_epoch: EpochNumber
    ) -> dict[str, Validator]:
        min_bucket_epoch = min(per_epoch_buckets.keys())
        min_bounded_epoch = max(min_bucket_epoch, EpochNumber(bound_with_epoch - EPOCHS_PER_SLASHINGS_VECTOR))
        bounded_slashed_validators: dict[str, Validator] = defaultdict(Validator)
        for epoch, slashed_validators in per_epoch_buckets.items():
            if min_bounded_epoch <= epoch <= bound_with_epoch:
                for key, validator in slashed_validators.items():
                    if key not in bounded_slashed_validators:
                        bounded_slashed_validators[key] = validator
        return bounded_slashed_validators

    def _get_per_frame_lido_midterm_penalties(
        self,
        per_epoch_lido_midterm_penalties: dict[EpochNumber, dict[str, Gwei]],
        frame_config: FrameConfig,
    ) -> list[Gwei]:
        """
        Put per epoch buckets into per frame buckets to calculate lido midterm penalties impact in each frame
        """
        per_frame_buckets: dict[int, dict[str, Gwei]] = defaultdict(dict)
        for epoch, validator_penalty in per_epoch_lido_midterm_penalties.items():
            frame_index = self._get_frame_by_epoch(epoch, frame_config)
            for val_key, penalty in validator_penalty.items():
                if val_key not in per_frame_buckets[frame_index]:
                    per_frame_buckets[frame_index][val_key] = penalty
        return [sum(penalties.values()) for penalties in per_frame_buckets.values()]

    @staticmethod
    def _get_frame_by_epoch(epoch: EpochNumber, frame_config: FrameConfig) -> int:
        return abs(epoch - frame_config.initial_epoch) // frame_config.epochs_per_frame

    @staticmethod
    def _calculate_normal_cl_rebase(
        epochs_passed: int, mean_total_lido_effective_balance: int, mean_total_effective_balance: int
    ) -> Gwei:
        normal_cl_rebase = int(
            (NORMALIZED_CL_PER_EPOCH * mean_total_lido_effective_balance * epochs_passed)
            / math.sqrt(mean_total_effective_balance) * (1 - NORMALIZED_CL_MISTAKE_PERCENT / 100)
        )
        return Gwei(normal_cl_rebase)
