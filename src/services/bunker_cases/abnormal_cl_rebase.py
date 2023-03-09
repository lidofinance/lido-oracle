import logging
import math

from statistics import mean

from web3.types import EventData

from src.constants import MAX_EFFECTIVE_BALANCE
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey
from src.services.bunker_cases.typings import BunkerConfig
from src.typings import ReferenceBlockStamp, Gwei, EpochNumber, BlockNumber, SlotNumber
from src.utils.slot import get_first_non_missed_slot
from src.utils.validator_state import calculate_active_effective_balance_sum
from src.web3py.extensions.lido_validators import LidoValidator, LidoValidatorsProvider
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class AbnormalClRebase:

    all_validators: list[Validator]
    lido_validators: list[LidoValidator]
    lido_keys: list[LidoKey]

    def __init__(self, w3: Web3, c_conf: ChainConfig, b_conf: BunkerConfig):
        self.w3 = w3
        self.c_conf = c_conf
        self.b_conf = b_conf

    def is_abnormal_cl_rebase(
        self,
        blockstamp: ReferenceBlockStamp,
        all_validators: list[Validator],
        lido_validators: list[LidoValidator],
        current_frame_cl_rebase: Gwei
    ) -> bool:
        self.all_validators = all_validators
        self.lido_validators = lido_validators
        self.lido_keys = self.w3.kac.get_all_lido_keys(blockstamp)

        logger.info({"msg": "Checking abnormal CL rebase"})

        normal_frame_cl_rebase = self._calculate_lido_normal_cl_rebase(blockstamp)

        if normal_frame_cl_rebase > current_frame_cl_rebase:
            logger.info({"msg": "CL rebase in frame is abnormal"})

            no_need_specific_cl_rebase_check = (
                self.b_conf.rebase_check_nearest_epoch_distance == 0 and
                self.b_conf.rebase_check_distant_epoch_distance == 0
            )
            if no_need_specific_cl_rebase_check:
                logger.info({"msg": "Specific CL rebase calculation are disabled. Cl rebase is abnormal"})
                return True

            if self._is_negative_specific_cl_rebase(blockstamp):
                return True

        return False

    def _calculate_lido_normal_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        """
        Calculate normal CL rebase for Lido validators (relative to all validators and the previous Lido frame)
        for current frame for Lido validators
        """
        last_report_blockstamp = self._get_last_report_blockstamp(blockstamp)

        epochs_passed_since_last_report = blockstamp.ref_epoch - last_report_blockstamp.ref_epoch

        last_report_all_validators = self.w3.cc.get_validators_no_cache(last_report_blockstamp)
        last_report_lido_validators = LidoValidatorsProvider.merge_validators_with_keys(
            self.lido_keys, last_report_all_validators
        )

        mean_all_effective_balance = AbnormalClRebase.get_mean_effective_balance_sum(
            last_report_blockstamp, blockstamp, last_report_all_validators, self.all_validators
        )
        mean_lido_effective_balance = AbnormalClRebase.get_mean_effective_balance_sum(
            last_report_blockstamp, blockstamp, last_report_lido_validators, self.lido_validators
        )

        normal_cl_rebase = AbnormalClRebase.calculate_normal_cl_rebase(
            self.b_conf, mean_all_effective_balance, mean_lido_effective_balance, epochs_passed_since_last_report
        )

        logger.info({"msg": f"Normal CL rebase: {normal_cl_rebase} Gwei"})
        return Gwei(normal_cl_rebase)

    def _is_negative_specific_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> bool:
        """
        Calculate CL rebase from nearest and distant epochs to ref epoch given the changes in withdrawal vault
        """
        logger.info({"msg": "Calculating nearest and distant CL rebase"})

        nearest_blockstamp, distant_blockstamp = self._get_nearest_and_distant_blockstamps(blockstamp)

        if nearest_blockstamp.block_number == distant_blockstamp.block_number:
            logger.info(
                {"msg": "Nearest and distant blocks are the same. Specific CL rebase will be calculated once"}
            )
            specific_cl_rebase = self._calculate_cl_rebase_between_blocks(nearest_blockstamp, blockstamp)
            logger.info({"msg": f"Specific CL rebase: {specific_cl_rebase} Gwei"})
            return specific_cl_rebase < 0

        nearest_cl_rebase = self._calculate_cl_rebase_between_blocks(nearest_blockstamp, blockstamp)
        logger.info({"msg": f"Nearest specific CL rebase {nearest_cl_rebase} Gwei"})
        if nearest_cl_rebase < 0:
            return True

        distant_cl_rebase = self._calculate_cl_rebase_between_blocks(distant_blockstamp, blockstamp)
        logger.info({"msg": f"Distant specific CL rebase {distant_cl_rebase} Gwei"})
        if distant_cl_rebase < 0:
            return True

        return False

    def _get_nearest_and_distant_blockstamps(
        self, blockstamp: ReferenceBlockStamp
    ) -> tuple[ReferenceBlockStamp, ReferenceBlockStamp]:
        """Get nearest and distant blockstamps. Calculation including missed slots"""
        nearest_slot = SlotNumber(
            blockstamp.slot_number - self.b_conf.rebase_check_nearest_epoch_distance * self.c_conf.slots_per_epoch
        )
        distant_slot = SlotNumber(
            blockstamp.slot_number - self.b_conf.rebase_check_distant_epoch_distance * self.c_conf.slots_per_epoch
        )

        AbnormalClRebase.validate_slot_distance(
            distant_slot, nearest_slot, blockstamp.slot_number
        )

        nearest_blockstamp = self._get_ref_blockstamp(needed=nearest_slot, finalized=blockstamp.slot_number)

        missed_slots = nearest_blockstamp.slot_number - nearest_slot

        distant_blockstamp = self._get_ref_blockstamp(
            needed=SlotNumber(distant_slot - missed_slots), finalized=blockstamp.slot_number
        )

        return nearest_blockstamp, distant_blockstamp

    def _calculate_cl_rebase_between_blocks(
        self, prev_blockstamp: ReferenceBlockStamp, curr_blockstamp: ReferenceBlockStamp
    ) -> Gwei:
        """
        Calculate CL rebase from prev_blockstamp to curr_blockstamp.
        Skimmed validator rewards are sent to 0x01 withdrawal credentials address
        which in Lido case is WithdrawalVault contract. To account for all changes in validators' balances,
        we must account for WithdrawalVault balance changes (withdrawn events from it)
        """
        logger.info(
            {"msg": f"Calculating CL rebase between {prev_blockstamp.ref_epoch, curr_blockstamp.ref_epoch} epochs"}
        )
        prev_lido_validators = LidoValidatorsProvider.merge_validators_with_keys(
            self.lido_keys,
            self.w3.cc.get_validators_no_cache(prev_blockstamp),
        )

        # Get Lido validators' balances with WithdrawalVault balance
        curr_lido_balance_with_vault = self._get_validators_balance_with_vault(curr_blockstamp, self.lido_validators)
        prev_lido_balance_with_vault = self._get_validators_balance_with_vault(prev_blockstamp, prev_lido_validators)

        # Raw CL rebase are calculated as difference between current and previous Lido validators' balances
        raw_cl_rebase = curr_lido_balance_with_vault - prev_lido_balance_with_vault

        # We should account validators who have been activated between blocks
        # And withdrawals from WithdrawalVault
        validators_count_diff_in_gwei = AbnormalClRebase.calculate_validators_count_diff_in_gwei(
            self.lido_validators, prev_lido_validators
        )
        withdrawn_from_vault = self._get_withdrawn_from_vault_between_blocks(prev_blockstamp, curr_blockstamp)

        # Finally, we can calculate corrected CL rebase
        cl_rebase = Gwei(raw_cl_rebase + validators_count_diff_in_gwei + withdrawn_from_vault)

        logger.info({
            "msg": f"CL rebase between {prev_blockstamp.ref_epoch,curr_blockstamp.ref_epoch} epochs: {cl_rebase} Gwei"
        })

        return cl_rebase

    def _get_validators_balance_with_vault(
        self, blockstamp: ReferenceBlockStamp, lido_validators: list[LidoValidator]
    ) -> Gwei:
        """
        Get Lido validator balance with withdrawals vault balance
        """
        real_cl_balance = AbnormalClRebase.calculate_real_balance(lido_validators)
        withdrawals_vault_balance = int(
            self.w3.from_wei(self.w3.lido_contracts.get_withdrawal_balance(blockstamp), "gwei")
        )
        return Gwei(real_cl_balance + withdrawals_vault_balance)

    def _get_withdrawn_from_vault_between_blocks(
        self, prev_blockstamp: ReferenceBlockStamp, curr_blockstamp: ReferenceBlockStamp
    ) -> int:
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
        """Get ETHDistributed events between blocks"""
        return self.w3.lido_contracts.lido.events.ETHDistributed.get_logs(
            fromBlock=from_block,
            toBlock=to_block,
        )

    def _get_last_report_blockstamp(self, blockstamp: ReferenceBlockStamp) -> ReferenceBlockStamp:
        """Get blockstamp of last report"""
        last_report_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(blockstamp)
        return self._get_ref_blockstamp(needed=last_report_ref_slot, finalized=blockstamp.slot_number)

    def _get_ref_blockstamp(self, needed: SlotNumber, finalized: SlotNumber) -> ReferenceBlockStamp:
        """Get blockstamp of needed slot"""
        return get_first_non_missed_slot(
            self.w3.cc,
            needed,
            ref_epoch=EpochNumber(needed // self.c_conf.slots_per_epoch),
            last_finalized_slot_number=finalized,
        )

    @staticmethod
    def calculate_validators_count_diff_in_gwei(curr_validators: list[Validator], prev_validators: list[Validator]):
        """Handle 32 ETH balances of freshly baked validators, who was activated between epochs"""
        validators_diff_in_gwei = (len(curr_validators) - len(prev_validators)) * MAX_EFFECTIVE_BALANCE
        if validators_diff_in_gwei < 0:
            raise ValueError("Validators count diff should be positive or 0. Something went wrong with CL API")
        return validators_diff_in_gwei

    @staticmethod
    def get_mean_effective_balance_sum(
        last_report_blockstamp: ReferenceBlockStamp,
        curr_blockstamp: ReferenceBlockStamp,
        last_report_validators: list[Validator],
        curr_validators: list[Validator],
    ) -> Gwei:
        """
        Calculate mean of effective balance sums
        """
        last_report_effective_balance_sum = calculate_active_effective_balance_sum(
            last_report_validators, last_report_blockstamp.ref_epoch
        )
        current_effective_balance_sum = calculate_active_effective_balance_sum(
            curr_validators, curr_blockstamp.ref_epoch
        )
        return mean((current_effective_balance_sum, last_report_effective_balance_sum))

    @staticmethod
    def validate_slot_distance(distant_slot: SlotNumber, nearest_slot: SlotNumber, current_slot: SlotNumber):
        if distant_slot <= nearest_slot <= current_slot:
            return
        raise ValueError(
            f"{nearest_slot=} should be between {distant_slot=} and {current_slot=} in specific CL rebase calculation"
        )

    @staticmethod
    def calculate_real_balance(validators: list[Validator]) -> Gwei:
        return Gwei(sum(int(v.balance) for v in validators))

    @staticmethod
    def calculate_normal_cl_rebase(
        bunker_config: BunkerConfig,
        mean_all_effective_balance_sum: int,
        mean_lido_effective_balance_sum: int,
        epochs_passed: int,
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
            (bunker_config.normalized_cl_reward_per_epoch * mean_lido_effective_balance_sum * epochs_passed)
            / math.sqrt(mean_all_effective_balance_sum) * (1 - bunker_config.normalized_cl_reward_mistake_rate)
        )
        return Gwei(normal_cl_rebase)
