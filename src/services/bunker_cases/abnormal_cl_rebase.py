import logging
import math

from typing import Sequence

from web3.types import EventData

from src.constants import MAX_EFFECTIVE_BALANCE, EFFECTIVE_BALANCE_INCREMENT
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator
from src.providers.keys.typings import LidoKey
from src.services.bunker_cases.typings import BunkerConfig
from src.typings import ReferenceBlockStamp, Gwei, BlockNumber, SlotNumber, BlockStamp, EpochNumber
from src.utils.slot import get_blockstamp, get_reference_blockstamp
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
        current_report_cl_rebase: Gwei
    ) -> bool:
        """
        First of all, we should calculate the normal CL rebase for this report
        If diff between current CL rebase and normal CL rebase more than `normalized_cl_reward_mistake_rate`,
        then we should check the intraframe sampled CL rebase: we consider two points (nearest and distant slots)
        in frame and calculate CL rebase for each of them and if one of them is negative, then it is abnormal CL rebase.

        `normalized_cl_reward_mistake_rate`, `rebase_check_nearest_epoch_distance` and `rebase_check_distant_epoch_distance`
        are configurable parameters, which can change behavior of this check.
        Like, don't check intraframe sampled CL rebase and look only on normal CL rebase
        """
        self.all_validators = all_validators
        self.lido_validators = lido_validators
        self.lido_keys = self.w3.kac.get_used_lido_keys(blockstamp)

        logger.info({"msg": "Checking abnormal CL rebase"})

        normal_report_cl_rebase = self._calculate_lido_normal_cl_rebase(blockstamp)
        diff_current_with_normal = 1 - current_report_cl_rebase / normal_report_cl_rebase

        if diff_current_with_normal > self.b_conf.normalized_cl_reward_mistake_rate:
            logger.info({"msg": "CL rebase in frame is abnormal"})

            no_need_intraframe_sampled_cl_rebase_check = (
                self.b_conf.rebase_check_nearest_epoch_distance == 0 and
                self.b_conf.rebase_check_distant_epoch_distance == 0
            )
            if no_need_intraframe_sampled_cl_rebase_check:
                logger.info({"msg": "Intraframe sampled CL rebase calculation are disabled. Cl rebase is abnormal"})
                return True

            if self._is_negative_specific_cl_rebase(blockstamp):
                return True

        return False

    def _calculate_lido_normal_cl_rebase(self, blockstamp: ReferenceBlockStamp) -> Gwei:
        """
        Calculate normal CL rebase for Lido validators (relative to all validators and the previous Lido frame)
        for current frame for Lido validators
        """
        last_report_blockstamp = self._get_last_report_reference_blockstamp(blockstamp)

        epochs_passed_since_last_report = blockstamp.ref_epoch - last_report_blockstamp.ref_epoch

        last_report_all_validators = self.w3.cc.get_validators_no_cache(last_report_blockstamp)
        last_report_lido_validators = LidoValidatorsProvider.merge_validators_with_keys(
            self.lido_keys, last_report_all_validators
        )

        mean_sum_of_all_effective_balance = AbnormalClRebase.get_mean_sum_of_effective_balance(
            last_report_blockstamp, blockstamp, last_report_all_validators, self.all_validators
        )
        mean_sum_of_lido_effective_balance = AbnormalClRebase.get_mean_sum_of_effective_balance(
            last_report_blockstamp, blockstamp, last_report_lido_validators, self.lido_validators
        )

        normal_cl_rebase = AbnormalClRebase.calculate_normal_cl_rebase(
            self.b_conf,
            mean_sum_of_all_effective_balance,
            mean_sum_of_lido_effective_balance,
            epochs_passed_since_last_report
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
                {"msg": "Nearest and distant blocks are the same. Intraframe sampled CL rebase will be calculated once"}
            )
            specific_cl_rebase = self._calculate_cl_rebase_between_blocks(nearest_blockstamp, blockstamp)
            logger.info({"msg": f"Intraframe sampled CL rebase: {specific_cl_rebase} Gwei"})
            return specific_cl_rebase < 0

        nearest_cl_rebase = self._calculate_cl_rebase_between_blocks(nearest_blockstamp, blockstamp)
        logger.info({"msg": f"Nearest intraframe sampled CL rebase {nearest_cl_rebase} Gwei"})
        if nearest_cl_rebase < 0:
            return True

        distant_cl_rebase = self._calculate_cl_rebase_between_blocks(distant_blockstamp, blockstamp)
        logger.info({"msg": f"Distant intraframe sampled CL rebase {distant_cl_rebase} Gwei"})
        if distant_cl_rebase < 0:
            return True

        return False

    def _get_nearest_and_distant_blockstamps(
        self, ref_blockstamp: ReferenceBlockStamp
    ) -> tuple[BlockStamp, BlockStamp]:
        """Get nearest and distant blockstamps by given reference blockstamp"""
        nearest_slot = SlotNumber(
            ref_blockstamp.ref_slot - self.b_conf.rebase_check_nearest_epoch_distance * self.c_conf.slots_per_epoch
        )
        distant_slot = SlotNumber(
            ref_blockstamp.ref_slot - self.b_conf.rebase_check_distant_epoch_distance * self.c_conf.slots_per_epoch
        )

        AbnormalClRebase.validate_slot_distance(
            distant_slot, nearest_slot, ref_blockstamp.slot_number
        )

        nearest_blockstamp = get_blockstamp(
            self.w3.cc, nearest_slot, last_finalized_slot_number=ref_blockstamp.slot_number
        )
        distant_blockstamp = get_blockstamp(
            self.w3.cc, distant_slot, last_finalized_slot_number=ref_blockstamp.slot_number
        )

        return nearest_blockstamp, distant_blockstamp

    def _calculate_cl_rebase_between_blocks(
        self, prev_blockstamp: BlockStamp, ref_blockstamp: ReferenceBlockStamp
    ) -> Gwei:
        """
        Calculate CL rebase from prev_blockstamp to ref_blockstamp.
        Skimmed validator rewards are sent to 0x01 withdrawal credentials address
        which in Lido case is WithdrawalVault contract.
        To account for all changes in validators' balances, we must account
        withdrawn events from WithdrawalVault contract.
        Check for these events is enough to account for all withdrawals since the protocol assumes that
        the vault can only be withdrawn at the time of the Oracle report between reference slots.
        """
        if prev_blockstamp.block_number == ref_blockstamp.block_number:
            # Can't calculate rebase between the same block
            return Gwei(0)

        prev_lido_validators = LidoValidatorsProvider.merge_validators_with_keys(
            self.lido_keys,
            self.w3.cc.get_validators_no_cache(prev_blockstamp),
        )

        # Get Lido validators' balances with WithdrawalVault balance
        ref_lido_balance_with_vault = self._get_lido_validators_balance_with_vault(
            ref_blockstamp, self.lido_validators
        )
        prev_lido_balance_with_vault = self._get_lido_validators_balance_with_vault(
            prev_blockstamp, prev_lido_validators
        )

        # Raw CL rebase is calculated as difference between reference and previous Lido validators' balances
        # Without accounting withdrawals from WithdrawalVault
        raw_cl_rebase = ref_lido_balance_with_vault - prev_lido_balance_with_vault

        # We should account validators who have been appeared between blocks
        validators_count_diff_in_gwei = AbnormalClRebase.calculate_validators_count_diff_in_gwei(
            prev_lido_validators, self.lido_validators
        )
        # And withdrawals from WithdrawalVault
        withdrawn_from_vault = self._get_withdrawn_from_vault_between_blocks(prev_blockstamp, ref_blockstamp)

        # Finally, we can calculate corrected CL rebase
        cl_rebase = Gwei(raw_cl_rebase + validators_count_diff_in_gwei + withdrawn_from_vault)

        logger.info({
            "msg": f"CL rebase between {prev_blockstamp.block_number,ref_blockstamp.block_number} blocks: {cl_rebase} Gwei"
        })

        return cl_rebase

    def _get_lido_validators_balance_with_vault(
        self, blockstamp: BlockStamp, lido_validators: list[LidoValidator]
    ) -> Gwei:
        """
        Get Lido validator balance with withdrawals vault balance
        """
        real_cl_balance = AbnormalClRebase.calculate_validators_balance_sum(lido_validators)
        withdrawals_vault_balance = int(
            self.w3.from_wei(self.w3.lido_contracts.get_withdrawal_balance_no_cache(blockstamp), "gwei")
        )
        return Gwei(real_cl_balance + withdrawals_vault_balance)

    def _get_withdrawn_from_vault_between_blocks(
        self, prev_blockstamp: BlockStamp, ref_blockstamp: ReferenceBlockStamp
    ) -> Gwei:
        """
        Lookup for ETHDistributed event and expect no one or only one event,
        from which we'll get withdrawalsWithdrawn value
        """

        logger.info(
            {"msg": f"Get withdrawn from vault between {prev_blockstamp.block_number,ref_blockstamp.block_number} blocks"}
        )

        events = self._get_eth_distributed_events(
            # We added +1 to prev block number because withdrawals from vault
            # are already counted in balance state on prev block number
            from_block=BlockNumber(int(prev_blockstamp.block_number) + 1),
            to_block=BlockNumber(int(ref_blockstamp.block_number)),
        )

        if len(events) > 1:
            raise ValueError("More than one ETHDistributed event found")

        if not events:
            logger.info({"msg": "No ETHDistributed event found. Vault withdrawals: 0 Gwei."})
            return Gwei(0)

        vault_withdrawals = int(self.w3.from_wei(events[0]['args']['withdrawalsWithdrawn'], 'gwei'))
        logger.info({"msg": f"Vault withdrawals: {vault_withdrawals} Gwei"})

        return Gwei(vault_withdrawals)

    def _get_eth_distributed_events(self, from_block: BlockNumber, to_block: BlockNumber) -> list[EventData]:
        """Get ETHDistributed events between blocks"""
        return self.w3.lido_contracts.lido.events.ETHDistributed.get_logs(  # type: ignore[attr-defined]
            fromBlock=from_block,
            toBlock=to_block,
        )

    def _get_last_report_reference_blockstamp(self, ref_blockstamp: ReferenceBlockStamp) -> ReferenceBlockStamp:
        """Get blockstamp of last report"""
        last_report_ref_slot = self.w3.lido_contracts.get_accounting_last_processing_ref_slot(ref_blockstamp)
        return get_reference_blockstamp(
            self.w3.cc,
            last_report_ref_slot,
            ref_epoch=EpochNumber(last_report_ref_slot // self.c_conf.slots_per_epoch),
            last_finalized_slot_number=ref_blockstamp.slot_number
        )

    @staticmethod
    def calculate_validators_count_diff_in_gwei(
        prev_validators: Sequence[Validator],
        ref_validators: Sequence[Validator],
    ) -> Gwei:
        """
        Handle 32 ETH balances of freshly baked validators, who was appeared between epochs
        Lido validators are counted by public keys that the protocol deposited with 32 ETH,
        so we can safely count the differences in the number of validators when they occur by deposit size.
        Any predeposits to Lido keys will not be counted until the key is deposited through the protocol
        and goes into `used` state
        """
        validators_diff = len(ref_validators) - len(prev_validators)
        if validators_diff < 0:
            raise ValueError("Validators count diff should be positive or 0. Something went wrong with CL API")
        return Gwei(validators_diff * MAX_EFFECTIVE_BALANCE)

    @staticmethod
    def get_mean_sum_of_effective_balance(
        last_report_blockstamp: ReferenceBlockStamp,
        ref_blockstamp: ReferenceBlockStamp,
        last_report_validators: Sequence[Validator],
        ref_validators: Sequence[Validator],
    ) -> Gwei:
        """
        Calculate mean of effective balance sums
        """
        last_report_effective_balance_sum = calculate_active_effective_balance_sum(
            last_report_validators, last_report_blockstamp.ref_epoch
        )
        ref_effective_balance_sum = calculate_active_effective_balance_sum(
            ref_validators, ref_blockstamp.ref_epoch
        )
        return Gwei((ref_effective_balance_sum + last_report_effective_balance_sum) // 2)

    @staticmethod
    def validate_slot_distance(distant_slot: SlotNumber, nearest_slot: SlotNumber, ref_slot: SlotNumber):
        if distant_slot <= nearest_slot <= ref_slot:
            return
        raise ValueError(
            f"{nearest_slot=} should be between {distant_slot=} and {ref_slot=} in specific CL rebase calculation"
        )

    @staticmethod
    def calculate_validators_balance_sum(validators: Sequence[Validator]) -> Gwei:
        return Gwei(sum(int(v.balance) for v in validators))

    @staticmethod
    def calculate_normal_cl_rebase(
        bunker_config: BunkerConfig,
        mean_sum_of_all_effective_balance: Gwei,
        mean_sum_of_lido_effective_balance: Gwei,
        epochs_passed: int,
    ) -> Gwei:
        """
        Calculate normal CL rebase for particular effective balance

        Actual value of `normal_cl_rebase` is a random variable with embedded variance for four reasons:
         * Calculating expected proposer rewards instead of actual - Randomness within specification
         * Calculating expected sync committee rewards instead of actual  - Randomness within specification
         * Instead of using data on active validators for each epoch
          estimation on number of active validators through interception of
          active validators between current oracle report epoch and last one - Randomness within measurement algorithm
         * Not absolutely ideal performance of Lido Validators and network as a whole  - Randomness of real world
        If the difference between observed real CL rewards and its theoretical value (normal_cl_rebase) couldn't be explained by
        those 4 factors that means there is an additional factor leading to lower rewards - incidents within Lido or BeaconChain.
        To formalize “high enough” difference we’re suggesting `normalized_cl_reward_per_epoch` constant
        represent ethereum specification and equals to `BASE_REWARD_FACTOR` constant
        """
        # It should be at least 1 ETH to avoid division by zero
        mean_sum_of_all_effective_balance = max(Gwei(EFFECTIVE_BALANCE_INCREMENT), mean_sum_of_all_effective_balance)
        normal_cl_rebase = int(
            (bunker_config.normalized_cl_reward_per_epoch * mean_sum_of_lido_effective_balance * epochs_passed)
            / math.sqrt(mean_sum_of_all_effective_balance)
        )
        return Gwei(normal_cl_rebase)
