from src.web3py.typings import Web3
from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import Validator
from src.modules.submodules.consensus import ChainConfig, FrameConfig

FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13

class SafeBorder:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.lido_contracts = w3.lido_contracts

    def get_safe_border_epoch(
        self, 
        is_bunker: bool, 
        blockstamp: BlockStamp, 
        chain_config: ChainConfig, 
        frame_config: FrameConfig
    ) -> int:
        if not is_bunker:
            return self._get_new_requests_border_epoch(blockstamp)

        self.chain_config = chain_config
        self.frame_config = frame_config

        self._retrieve_constants()
        
        negative_rebase_border_epoch = self._get_negative_rebase_border_epoch(blockstamp)
        associated_slashings_border_epoch = self._get_associated_slashings_border_epoch(blockstamp)

        return min(
            negative_rebase_border_epoch,
            associated_slashings_border_epoch
        )

    def _get_new_requests_border_epoch(self, blockstamp: BlockStamp) -> int:
        return self.get_epoch_by_slot(blockstamp.ref_slot) - self.finalization_default_shift

    def _get_negative_rebase_border_epoch(self, blockstamp: BlockStamp) -> int:
        bunker_start_or_last_successful_report_epoch = self._get_bunker_start_or_last_successful_report_epoch(blockstamp)

        latest_allowable_epoch = bunker_start_or_last_successful_report_epoch - self.finalization_default_shift
        earliest_allowable_epoch = self.get_epoch_by_slot(blockstamp.ref_slot) - self.finalization_max_negative_rebase_shift

        return max(earliest_allowable_epoch, latest_allowable_epoch)

    def _get_bunker_start_or_last_successful_report_epoch(self, blockstamp: BlockStamp):
        bunker_start_timestamp = self._get_bunker_mode_start_timestamp(blockstamp)

        if bunker_start_timestamp is None:
            return self.get_epoch_by_slot(self._get_last_successful_report_slot(blockstamp))

        return self.get_epoch_by_timestamp(bunker_start_timestamp)

    def _get_associated_slashings_border_epoch(self, blockstamp: BlockStamp) -> int:
        earliest_slashed_epoch = self._get_earliest_slashed_epoch_among_incomplete_slashings(blockstamp)

        if earliest_slashed_epoch is None:
            return self.get_epoch_by_slot(blockstamp.ref_slot) - self.finalization_default_shift
        
        return self.round_epoch_by_frame(earliest_slashed_epoch) - self.finalization_default_shift

    def _get_earliest_slashed_epoch_among_incomplete_slashings(self, blockstamp: BlockStamp) -> int:
        validators = self._get_lido_validators(blockstamp)
        validators_slashed = filter_slashed_validators(validators)

        # Here we filter not by exit_epoch but by withdrawable_epoch because exited operators can still be slashed.
        # See more here https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#helpers
        # at `get_eligible_validator_indices` method.
        validators_slashed_non_withdrawable = filter_non_withdrawable_validators(validators_slashed, blockstamp.ref_slot)
        
        if len(validators_slashed_non_withdrawable) == 0:
            return None
        
        validators_with_earliest_exit_epoch = self._filter_validators_with_earliest_exit_epoch(validators_slashed_non_withdrawable)
        
        validators_earliest_slashed_epochs_predicted = list(map(self._predict_earliest_slashed_epoch, validators_with_earliest_exit_epoch))
        slashed_epochs_unpredictable = list(filter(lambda e: e is None, validators_earliest_slashed_epochs_predicted))
        earliest_slashed_epoch_predicted = list(sorted(filter(lambda e: e is not None, validators_earliest_slashed_epochs_predicted)))

        if len(slashed_epochs_unpredictable) == 0:
            return earliest_slashed_epoch_predicted[0]
        return self._find_earliest_slashed_epoch(validators_with_earliest_exit_epoch, blockstamp)

    # If there are no so many validators in exit queue we can be quite sure that
    # slashing has started not earlier than 8,192 epochs or ~36 days ago
    def _predict_earliest_slashed_epoch(self, validator) -> int:
        exit_epoch = int(validator.validator.exit_epoch)
        withdrawable_epoch = int(validator.validator.withdrawable_epoch)

        exited_period = withdrawable_epoch - exit_epoch
        is_slashed_epoch_undetectable = exited_period > MIN_VALIDATOR_WITHDRAWABILITY_DELAY
        if is_slashed_epoch_undetectable:
            return None

        return withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR

    def _find_earliest_slashed_epoch(self, validators, blockstamp: BlockStamp) -> int:
        pubkeys = get_validators_pubkeys(validators)
        withdrawable_epoch = min(get_validators_withdrawable_epochs(validators))

        last_finalized_request_id_slot = self._get_last_finalized_withdrawal_request_slot(blockstamp)

        start_slot = max(last_finalized_request_id_slot, self.get_epoch_first_slot(self._get_validators_earliest_activation_epoch(validators)))
        end_slot = min(blockstamp.ref_slot, self.get_epoch_first_slot(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR))

        while self._check_slot_diff(start_slot, end_slot):
            mid_slot = (end_slot + start_slot) // 2
            validators = self._get_archive_lido_validators_by_keys(mid_slot, pubkeys)
            slashed_validators = filter_slashed_validators(validators)

            if len(slashed_validators) > 0:
                end_slot = mid_slot - 1
                pubkeys = get_validators_pubkeys(slashed_validators)
            else:
                start_slot = mid_slot + 1

        return self.get_epoch_by_slot(start_slot)

    def _check_slot_diff(self, start_slot: int, end_slot: int):
        return self.get_frame_by_slot(start_slot) == self.get_frame_by_slot(end_slot)

    def _filter_validators_with_earliest_exit_epoch(self, validators) -> list[Validator]:
        if len(validators) == 0:
            return []

        sorted_validators = sorted(validators, key = lambda validator: (int(validator.validator.exit_epoch)))
        earliest_exit_epoch = sorted_validators[0].validator.exit_epoch
        return filter_validators_by_exit_epoch(sorted_validators, earliest_exit_epoch)

    def _get_validators_earliest_activation_epoch(self, validators) -> int:
        if len(validators) == 0:
            return 0

        sorted_validators = sorted(validators, key = lambda validator: (int(validator.validator.validator.activation_epoch)))
        return sorted_validators[0].validator.validator.activation_epoch
    
    def _get_bunker_mode_start_timestamp(self, blockstamp: BlockStamp) -> int:
        start_timestamp = self._get_bunker_start_timestamp()
        
        if start_timestamp > blockstamp.ref_slot:
            return None

        return start_timestamp

    def _get_last_finalized_withdrawal_request_slot(self, blockstamp: BlockStamp) -> int:
        last_finalized_request_id = self._get_last_finalized_request_id(blockstamp)
        if last_finalized_request_id == 0:
            return 0

        last_finalized_request_data = self._get_withdrawal_request_status(last_finalized_request_id, blockstamp)

        return self.get_epoch_first_slot(self.get_epoch_by_timestamp(last_finalized_request_data.timestamp))
    
    def _get_bunker_start_timestamp(self, blockstamp: BlockStamp):
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.bunkerModeSinceTimestamp().call(block_identifier=blockstamp.block_hash)
    
    def _get_last_finalized_request_id(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getLastFinalizedRequestId().call(block_identifier=blockstamp.block_hash)

    def _get_withdrawal_request_status(self, request_id: int, blockstamp: BlockStamp) -> any:
        return self.w3.lido_contracts.withdrawal_queue_nft.functions.getWithdrawalRequestStatus(request_id).call(block_identifier=blockstamp.block_hash)

    def _get_lido_validators(self, blockstamp: BlockStamp) -> list[Validator]:
        return [lv.validator for lv in self.w3.lido_validators.get_lido_validators(blockstamp.ref_slot)]

    def _get_archive_lido_validators_by_keys(self, slot, pubkeys) -> list[Validator]:
        return self.w3.cc.get_validators(slot, pubkeys)

    def _get_last_successful_report_slot(self, blockstamp: BlockStamp) -> int:
        return self.w3.lido_contracts.report_contract.functions.getLastProcessingRefSlot().call(block_identifier=blockstamp.block_hash)

    def _retrieve_constants(self, blockstamp: BlockStamp):
        self.finalization_default_shift = self.w3.lido_contracts.oracle_daemon_config.functions.get(
             'FINALIZATION_DEFAULT_SHIFT'
        ).call(block_identifier=blockstamp.block_hash)
        self.finalization_max_negative_rebase_shift = self.w3.lido_contracts.oracle_daemon_config.functions.get(
             'FINALIZATION_MAX_NEGATIVE_REBASE_SHIFT'
        ).call(block_identifier=blockstamp.block_hash)

    def get_epoch_first_slot(self, epoch: int) -> int:
        return epoch * self.chain_config.slots_per_epoch

    def get_epoch_by_slot(self, ref_slot: int) -> int:
        return ref_slot // self.chain_config.slots_per_epoch

    def get_epoch_by_timestamp(self, timestamp: int) -> int:
        return self.get_slot_by_timestamp(timestamp) // self.chain_config.slots_per_epoch

    def get_slot_by_timestamp(self, timestamp: int) -> int:
        return (timestamp - self.chain_config.genesis_time) // self.chain_config.seconds_per_slot

    def round_epoch_by_frame(self, epoch: int) -> int:
        return self.get_frame_by_epoch(epoch) * self.frame_config.epochs_per_frame + self.frame_config.initial_epoch

    def get_frame_by_slot(self, slot):
        return self.get_frame_by_epoch(self.get_epoch_by_slot(slot))

    def get_frame_by_epoch(self, epoch: int) -> int:
        return abs(epoch - self.frame_config.initial_epoch) // self.frame_config.epochs_per_frame

    

# TODO: stop converting back to list
def filter_slashed_validators(validators: Validator) -> list[Validator]:
    return list(filter(lambda validator: validator.validator.slashed, validators))
def filter_non_withdrawable_validators(validators: list[Validator], epoch: int) -> list[Validator]:
    return list(filter(lambda validator: int(validator.validator.withdrawable_epoch) > epoch, validators)) 
def filter_validators_by_exit_epoch(validators: list[Validator], exit_epoch: int) -> list[Validator]:
    return list(filter(lambda validator: validator.validator.exit_epoch == exit_epoch, validators)) 
def get_validators_pubkeys(validators: list[Validator]) -> list[str]:
    return list(map(lambda validator: validator.validator.pubkey, validators))
def get_validators_withdrawable_epochs(validators: list[Validator]) -> list[int]:
    return list(map(lambda validator: int(validator.validator.withdrawable_epoch), validators))