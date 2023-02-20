from src.web3py.typings import Web3
from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import LidoValidator

DEFAULT_SHIFT = 8 # epochs ~50 min
MAX_NEGATIVE_REBASE_SHIFT = 1536 # epochs ~6.8 days
FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
SLOTS_PER_EPOCH = 2**5

class SafeBorder:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.lido_contracts = w3.lido_contracts

    def get_safe_border_epoch(self, is_bunker: bool, blockstamp: BlockStamp):
        if not is_bunker:
            return self._get_new_requests_border_epoch(blockstamp)
        
        negative_rebase_border_epoch = self._get_negative_rebase_border_epoch(blockstamp)
        associated_slashings_border_epoch = self._get_associated_slashings_border_epoch(blockstamp)

        return min(
            negative_rebase_border_epoch,
            associated_slashings_border_epoch
        )

    def _get_new_requests_border_epoch(self, blockstamp: BlockStamp):
        return get_epoch_by_slot(blockstamp.slot_number) - DEFAULT_SHIFT

    def _get_negative_rebase_border_epoch(self, blockstamp: BlockStamp):  
        bunker_start_timestamp = self._get_bunker_mode_start_timestamp(blockstamp)
        bunker_start_epoch = get_epoch_by_timestamp(bunker_start_timestamp)

        bunker_start_border_epoch = bunker_start_epoch - DEFAULT_SHIFT
        earliest_allowable_epoch = get_epoch_by_slot(blockstamp.slot_number) - MAX_NEGATIVE_REBASE_SHIFT

        return max(earliest_allowable_epoch, bunker_start_border_epoch)

    def _get_associated_slashings_border_epoch(self, blockstamp: BlockStamp):
        earliest_slashed_epoch = self._get_earliest_slashed_epoch_among_incomplete_slashings(blockstamp)

        if earliest_slashed_epoch is None:
            return get_epoch_by_slot(blockstamp.slot_number) - DEFAULT_SHIFT
        
        return earliest_slashed_epoch - DEFAULT_SHIFT

    def _get_earliest_slashed_epoch_among_incomplete_slashings(self, blockstamp: BlockStamp):
        validators = self._get_lido_validators(blockstamp)       
        validators_slashed = filter_slashed_validators(validators)
        validators_slashed_non_withdrawable = filter_non_withdrawable_validators(validators_slashed, blockstamp.slot_number)

        if len(validators_slashed_non_withdrawable) == 0:
            return None

        validators_with_earliest_exit_epoch = self._filter_validators_with_earliest_exit_epoch(validators_slashed_non_withdrawable)
        earliest_slashed_epoch_predicted = self._predict_earliest_slashed_epoch(validators_with_earliest_exit_epoch[0])

        if earliest_slashed_epoch_predicted is not None:
            return earliest_slashed_epoch_predicted
        return self._find_earliest_slashed_epoch(validators_with_earliest_exit_epoch, blockstamp.slot_number)

    def _filter_validators_with_earliest_exit_epoch(self, validators):
        if len(validators) == 0:
            return []

        sorted_validators = sorted(validators, key = lambda validator: (int(validator.validator.validator.exit_epoch)))
        earliest_exit_epoch = sorted_validators[0].validator.validator.exit_epoch
        return filter_validators_by_exit_epoch(sorted_validators, earliest_exit_epoch)

    # If there is no so many exited validators in line we can be quite sure that
    # slashing has started not earlier than 8,192 epochs or ~36 days ago
    def _predict_earliest_slashed_epoch(self, validator):
        exit_epoch = int(validator.validator.validator.exit_epoch)
        withdrawable_epoch = int(validator.validator.validator.withdrawable_epoch)

        exited_period = withdrawable_epoch - exit_epoch
        is_slashed_epoch_undetectable = exited_period > MIN_VALIDATOR_WITHDRAWABILITY_DELAY
        if is_slashed_epoch_undetectable:
            return None

        return withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR

    def _find_earliest_slashed_epoch(self, validators, ref_slot):
        pubkeys = get_validators_pubkeys(validators)
        withdrawable_epoch = min(get_validators_withdrawable_epochs(validators))

        start_slot = 0
        end_slot = min(ref_slot, get_epoch_first_slot(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR))

        while start_slot + 1 < end_slot:
            mid_slot = (end_slot + start_slot) // 2
            validators = self._get_archive_lido_validators_by_keys(mid_slot, pubkeys)
            slashed_validators = filter_slashed_validators(validators)

            if len(slashed_validators) > 0:
                end_slot = mid_slot - 1
            else:
                start_slot = mid_slot + 1

        return get_epoch_by_slot(end_slot)

    def _get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        return self.w3.cc.get_validators(blockstamp.slot_number)

    def _get_archive_lido_validators_by_keys(self, slot_number, pubkeys):
        return self.w3.cc.get_validators(slot_number, tuple(pubkeys))

    def _get_bunker_mode_start_timestamp(self, blockstamp: BlockStamp) -> str:
        return self.w3.lido_contracts.withdrawal_queue.functions.bunkerModeSinceTimestamp().call(block_identifier=blockstamp.block_hash)

def get_epoch_first_slot(epoch: int):
    return epoch * SLOTS_PER_EPOCH

def get_epoch_by_slot(slot_number: int):
    return slot_number // SLOTS_PER_EPOCH

def get_epoch_by_timestamp(timestamp: int):
    return timestamp // (SLOTS_PER_EPOCH * 12)
                

# TODO: stop converting back to list
def filter_slashed_validators(validators):
    return list(filter(lambda validator: validator.validator.validator.slashed, validators))
def filter_non_withdrawable_validators(validators, epoch):
    return list(filter(lambda validator: int(validator.validator.validator.withdrawable_epoch) > epoch, validators)) 
def filter_validators_by_exit_epoch(validators, exit_epoch):
    return list(filter(lambda validator: validator.validator.validator.exit_epoch == exit_epoch, validators)) 
def get_validators_pubkeys(validators):
    return list(map(lambda validator: validator.validator.validator.pubkey, validators))
def get_validators_withdrawable_epochs(validators):
    return list(map(lambda validator: int(validator.validator.validator.withdrawable_epoch), validators))