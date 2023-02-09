import math
import logging
from typing import List, Sequence

from ens.utils import Web3

from src.modules.accounting.typings import CommonDataToProcess, Gwei, Epoch
from src.modules.submodules.consensus import ConsensusModule, FrameConfig, ChainConfig
from src.providers.consensus.typings import ValidatorStatus, Validator
from src.typings import BlockStamp, SlotNumber

MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 256
EPOCHS_PER_SLASHINGS_VECTOR = 8192
PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX = 3
EFFECTIVE_BALANCE_INCREMENT = 2 ** 0 * 10 ** 9
MIN_DEPOSIT_AMOUNT = 32 * 10 ** 9

FIRST_DEPOSIT_EVENT_LOOKUP_MAXIMUM_BLOCKS_DISTANCE = 225 * 7

NORMILIZED_CL_PER_EPOCH = 64
MISTAKE_RANGE = 0.1
NEAREST_EPOCH_DISTANCE = 4
FAR_EPOCH_DISTANCE = 25

logger = logging.getLogger(__name__)


class BunkerService:

    def __init__(self, w3: Web3, frame_config: FrameConfig, chain_config: ChainConfig):
        self.w3 = w3
        self.cm = ConsensusModule(self.w3)
        self.f_conf = frame_config
        self.c_conf = chain_config

    def is_bunker_mode(self, cdtp: CommonDataToProcess) -> bool:
        logger.info({"msg": "Checking bunker mode"})
        frame_cl_rebase = self._get_cl_rebase_for_frame(cdtp)
        if frame_cl_rebase < 0:
            logger.info({"msg": "Bunker ON. CL rebase is negative"})
            return True
        if self._is_high_midterm_slashing_penalty(cdtp, frame_cl_rebase):
            logger.info({"msg": "Bunker ON. High midterm slashing penalty"})
            return True
        if self._is_abnormal_cl_rebase(cdtp, frame_cl_rebase):
            logger.info({"msg": "Bunker ON. Abnormal CL rebase"})
            return True

    def _get_cl_rebase_for_frame(self, cdtp: CommonDataToProcess) -> Gwei:
        logger.info({"msg": "Getting CL rebase for frame"})
        ref_lido_balance, ref_withdrawal_vault_balance = self._calculate_lido_balance_with_vault(
            cdtp.ref_blockstamp, [v.validator for v in cdtp.ref_lido_validators], cdtp.ref_blockstamp
        )
        # Make a static call of 'handleOracleReport' without EL rewards
        # to simulate report and get total pool ether after that
        args = {
            "_reportTimestamp": cdtp.ref_timestamp,
            "_timeElapsed": cdtp.seconds_elapsed_since_last_report,
            "_clValidators": len(cdtp.ref_lido_validators),
            "_clBalance": self.w3.to_wei(ref_lido_balance, 'gwei'),
            "_withdrawalVaultBalance": ref_withdrawal_vault_balance,
            "_elRewardsVaultBalance": 0,
            "_lastFinalizableRequestId": 0,
            "_simulatedShareRate": 0,
        }
        before_report_total_pooled_ether = self.w3.lido_contracts.lido.functions.totalSupply().call(
            block_identifier=cdtp.ref_blockstamp.block_hash
        )
        after_report_total_pooled_ether, _ = self.w3.lido_contracts.lido.functions.handleOracleReport(**args).call(
            block_identifier=cdtp.ref_blockstamp.block_hash
        )
        logger.info({
            "msg": "Simulate 'handleOracleReport' contract function call",
            "call_args": args,
            "before_call": before_report_total_pooled_ether,
            "after_call": after_report_total_pooled_ether,
        })

        frame_cl_rebase = self.w3.from_wei(after_report_total_pooled_ether - before_report_total_pooled_ether, 'gwei')
        logger.info({"msg": f"Simulated CL rebase for frame: {frame_cl_rebase} Gwei"})

        return frame_cl_rebase

    def _is_high_midterm_slashing_penalty(self, cdtp: CommonDataToProcess, cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Detecting high midterm slashing penalty"})
        all_slashed_validators = self._not_withdrawn_slashed_validators(cdtp.ref_all_validators, cdtp.ref_epoch)
        lido_slashed_validators: List[Validator] = [
            v.validator for v in self.w3.lido_validators.filter_lido_validators(cdtp.lido_keys, all_slashed_validators)
        ]
        logger.info({"msg": f"Slashed - all: {len(all_slashed_validators)} lido: {len(lido_slashed_validators)}"})

        # If no one lido in current slashed validators - no need to bunker
        if len(lido_slashed_validators) == 0:
            return False

        # Fill per epoch buckets by possible slashed epochs
        per_epoch_buckets: dict[int, List[Validator]] = {}
        for validator in all_slashed_validators:
            possible_epochs_with_slashings = self._detect_slashing_epoch_range(validator, cdtp.ref_epoch)
            for epoch in possible_epochs_with_slashings:
                per_epoch_buckets[epoch] = per_epoch_buckets.get(epoch, []) + [validator]

        # Iterate through per_epoch_buckets and calculate lido midterm penalties for each bucket
        per_epoch_lido_midterm_penalties: dict[int, int] = {}
        # We should calculate total_balance for each bucket, but we do it once for all per_epoch_buckets
        total_balance = self._calculate_total_effective_balance(cdtp.ref_all_validators)
        for epoch, slashed_validators in per_epoch_buckets.items():
            slashed_keys = [k.validator.pubkey for k in slashed_validators]
            lido_validators_slashed_in_epoch = [
                v for v in lido_slashed_validators if v.validator.pubkey in slashed_keys
            ]
            if len(lido_validators_slashed_in_epoch) == 0:
                continue
            # We should calculate penalties according to bounded slashings in past EPOCHS_PER_SLASHINGS_VECTOR
            bounded_slashings_balance_sum = 0  # aka state.slashings from spec
            min_bounded_epoch = max(
                min(per_epoch_buckets.keys()), epoch - EPOCHS_PER_SLASHINGS_VECTOR
            )
            bounded_epochs = [e for e in per_epoch_buckets if min_bounded_epoch <= e <= epoch]
            for e in bounded_epochs:
                bounded_slashings_balance_sum += sum(
                    [int(v.validator.effective_balance) for v in per_epoch_buckets[e]]
                )
            adjusted_total_slashing_balance = min(
                bounded_slashings_balance_sum * PROPORTIONAL_SLASHING_MULTIPLIER_BELLATRIX,
                total_balance
            )
            for v in lido_validators_slashed_in_epoch:
                effective_balance = int(v.validator.effective_balance)
                penalty_numerator = effective_balance // EFFECTIVE_BALANCE_INCREMENT * adjusted_total_slashing_balance
                penalty = penalty_numerator // total_balance * EFFECTIVE_BALANCE_INCREMENT
                per_epoch_lido_midterm_penalties[epoch] = per_epoch_lido_midterm_penalties.get(epoch, 0) + penalty

        # Put per epoch buckets into per frame buckets to calculate lido midterm penalties impact in each frame
        per_frame_buckets: dict[int, int] = {}
        index = 0
        right_border = self.f_conf.initial_epoch + self.f_conf.epochs_per_frame
        # The first bucket should have flexible size. It can be less than 'epochs_per_frame'
        while right_border < min(per_epoch_lido_midterm_penalties.keys()):
            right_border += self.f_conf.epochs_per_frame
        left_border = min(per_epoch_lido_midterm_penalties.keys())
        # This will give us something like
        # |                      0               |       1       |       2       |      N             |
        #   min_bucket_epoch (eg. 1520) ... 1575   1576 ... 1801   1802 ... 2027     n ... n + frame
        for epoch, midterm_penalty_sum in sorted(per_epoch_lido_midterm_penalties.items()):
            if epoch > right_border:
                index += 1
                left_border = right_border + 1
                right_border += self.f_conf.epochs_per_frame
            if left_border <= epoch <= right_border:
                per_frame_buckets[index] = per_frame_buckets.get(index, 0) + midterm_penalty_sum

        # If any midterm penalty sum of lido validators in frame bucket greater than rebase we should trigger bunker
        max_lido_midterm_penalty = max(per_frame_buckets.values())
        logger.info({"msg": f"Max lido midterm penalty: {max_lido_midterm_penalty}"})
        if max_lido_midterm_penalty > cl_rebase:
            return True

        return False

    def _is_abnormal_cl_rebase(self, cdtp: CommonDataToProcess, frame_cl_rebase: Gwei) -> bool:
        logger.info({"msg": "Checking abnormal CL rebase"})
        normal_cl_rebase = self._calculate_normal_cl_rebase(cdtp)
        if frame_cl_rebase < normal_cl_rebase:
            logger.info({"msg": "Abnormal CL rebase in frame"})
            nearest_cl_rebase, far_cl_rebase = self._calculate_nearest_and_far_cl_rebase(cdtp)
            if nearest_cl_rebase < 0 or far_cl_rebase < 0:
                return True
        return False

    def _calculate_normal_cl_rebase(self, cdtp: CommonDataToProcess) -> Gwei:
        """
        Calculate normal CL rebase (relative to all validators and the previous Lido frame)
        for current frame for Lido validators
        """
        last_report_blockstamp = self.cm.get_first_non_missed_slot(cdtp.ref_blockstamp, cdtp.last_report_ref_slot)

        total_ref_effective_balance = self._calculate_total_effective_balance(cdtp.ref_all_validators)
        total_ref_lido_effective_balance = self._calculate_total_effective_balance(
            [v.validator for v in cdtp.ref_lido_validators]
        )

        if cdtp.last_report_ref_epoch <= self.f_conf.initial_epoch:
            # If no one report was made - we should use initial epoch as last completed epoch
            # Because in this case 'cl_rebase' will contain all rewards from initial epoch
            last_completed_epoch = self.f_conf.initial_epoch
            total_last_effective_balance = total_ref_effective_balance
            total_last_lido_effective_balance = total_ref_lido_effective_balance
        else:
            last_completed_epoch = cdtp.last_report_ref_epoch
            last_all_validators = self.w3.cc.get_validators(last_report_blockstamp.state_root)
            last_lido_validators = self.w3.lido_validators.filter_lido_validators(cdtp.lido_keys, last_all_validators)
            total_last_effective_balance = self._calculate_total_effective_balance(last_all_validators)
            total_last_lido_effective_balance = self._calculate_total_effective_balance(
                [v.validator for v in last_lido_validators]
            )

        mean_total_effective_balance = (total_ref_effective_balance + total_last_effective_balance) // 2
        mean_total_lido_effective_balance = (
            (total_ref_lido_effective_balance + total_last_lido_effective_balance) // 2
        )

        epochs_passed = cdtp.ref_epoch - last_completed_epoch
        normal_cl_rebase = int(
            (NORMILIZED_CL_PER_EPOCH * mean_total_lido_effective_balance * epochs_passed)
            // (math.sqrt(mean_total_effective_balance) * (1 - MISTAKE_RANGE))
        )

        logger.info({"msg": f"Normal CL rebase: {normal_cl_rebase} Gwei"})
        return normal_cl_rebase

    def _calculate_nearest_and_far_cl_rebase(self, cdtp: CommonDataToProcess) -> tuple[Gwei, Gwei]:
        """
        Calculate CL rebase from nearest and far epochs to ref epoch given the changes in withdrawal vault
        """
        logger.info({"msg": "Calculating nearest and far CL rebase"})
        nearest_slot = (cdtp.ref_blockstamp.slot_number - NEAREST_EPOCH_DISTANCE * self.c_conf.slots_per_epoch)
        far_slot = (cdtp.ref_blockstamp.slot_number - FAR_EPOCH_DISTANCE * self.c_conf.slots_per_epoch)
        nearest_blockstamp = self.cm.get_first_non_missed_slot(cdtp.ref_blockstamp, SlotNumber(nearest_slot))
        far_blockstamp = self.cm.get_first_non_missed_slot(cdtp.ref_blockstamp, SlotNumber(far_slot))
        nearest_cl_rebase = self._calculate_cl_rebase_from(cdtp, nearest_blockstamp)
        far_cl_rebase = self._calculate_cl_rebase_from(cdtp, far_blockstamp)

        logger.info({"msg": f"CL rebase {nearest_cl_rebase,far_cl_rebase=}"})
        return nearest_cl_rebase, far_cl_rebase

    def _calculate_cl_rebase_from(self, cdtp: CommonDataToProcess, prev_blockstamp: BlockStamp) -> Gwei:
        """
        Calculate CL rebase from prev_blockstamp to ref_blockstamp given the changes in withdrawal vault
        """
        prev_epoch = prev_blockstamp.slot_number // self.c_conf.slots_per_epoch
        logger.info({"msg": f"Calculating CL rebase between {prev_epoch,cdtp.ref_epoch=}"})

        ref_lido_balance_with_vault = sum(self._calculate_lido_balance_with_vault(
            cdtp.ref_blockstamp, [v.validator for v in cdtp.ref_lido_validators], cdtp.ref_blockstamp
        ))

        prev_all_validators = self.w3.cc.get_validators(prev_blockstamp.state_root)
        prev_lido_validators = self.w3.lido_validators.filter_lido_validators(cdtp.lido_keys, prev_all_validators)
        prev_lido_balance_with_vault = sum(self._calculate_lido_balance_with_vault(
            cdtp.ref_blockstamp, [v.validator for v in prev_lido_validators], prev_blockstamp
        ))

        # handle 32 ETH balances of freshly baked validators, who was activated between epochs
        validators_diff_in_gwei = (len(cdtp.ref_lido_validators) - len(prev_lido_validators)) * MIN_DEPOSIT_AMOUNT
        assert validators_diff_in_gwei >= 0, "Validators diff should be positive or 0. Something went wrong with CL API"

        corrected_prev_lido_balance_with_vault = (
            prev_lido_balance_with_vault
            + validators_diff_in_gwei
            - self._get_withdrawn_from_vault_between(prev_blockstamp, cdtp.ref_blockstamp)
        )

        cl_rebase = ref_lido_balance_with_vault - corrected_prev_lido_balance_with_vault

        logger.info({"msg": f"CL rebase from {prev_epoch=}: {cl_rebase} Gwei"})

        return cl_rebase

    def _calculate_lido_balance_with_vault(
        self, ref_blockstamp: BlockStamp, lido_validators: List[Validator], vault_balance_at: BlockStamp
    ) -> tuple[Gwei, Gwei]:
        """
        Calculate Lido validators balance and balance in withdrawal vault contract in particular block
        """
        lido_balance = sum([int(validator.balance) for validator in lido_validators])
        withdrawal_vault_balance = self.w3.from_wei(
            self.w3.eth.get_balance(
                self.w3.lido_contracts.lido_locator.functions.withdrawalVault().call(
                    block_identifier=ref_blockstamp.block_hash
                ), vault_balance_at.block_hash
            ),
            'gwei'
        )
        return lido_balance, withdrawal_vault_balance

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

    @staticmethod
    def _calculate_total_effective_balance(all_validators: List[Validator]) -> Gwei:
        """
        Calculates total balance of all active validators in network
        """
        total_effective_balance = 0

        for validator in all_validators:
            if validator.status in [
                ValidatorStatus.ACTIVE_ONGOING.value,
                ValidatorStatus.ACTIVE_EXITING.value,
                ValidatorStatus.ACTIVE_SLASHED.value
            ]:
                validator_effective_balance = validator.validator.effective_balance
                total_effective_balance += int(validator_effective_balance)

        return total_effective_balance

    @staticmethod
    def _not_withdrawn_slashed_validators(all_validators: List[Validator], ref_epoch: Epoch) -> List[Validator]:
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
    def _detect_slashing_epoch_range(validator: Validator, ref_epoch: Epoch) -> Sequence[Epoch]:
        """
        Detect slashing epoch range for validator
        If difference between validator's withdrawable epoch and exit epoch is greater enough,
        then we can be sure that validator was slashed in particular epoch
        Otherwise, we can only assume that validator was slashed in epochs range
        due because its exit epoch shifted because of huge exit queue
        Read more here: https://hackmd.io/@lido/r1Qkkiv3j
        """
        is_known_slashed_epoch = False

        v = validator.validator
        if int(v.withdrawable_epoch) - int(v.exit_epoch) > MIN_VALIDATOR_WITHDRAWABILITY_DELAY:
            is_known_slashed_epoch = True
        possible_slashed_epoch = int(v.withdrawable_epoch) - EPOCHS_PER_SLASHINGS_VECTOR

        if is_known_slashed_epoch:
            return range(possible_slashed_epoch, possible_slashed_epoch + 1)

        return range(possible_slashed_epoch, ref_epoch + 1)
