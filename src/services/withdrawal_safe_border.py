from math import trunc
from src.web3_extentions.typings import Web3
from src.typings import BlockStamp
from src.web3_extentions.lido_validators import LidoValidator, LidoValidatorsProvider

NEW_REQUESTS_BORDER = 8 # epochs ~50 min
MAX_NEGATIVE_REBASE_BORDER = 1536 # epochs ~6.8 days
FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
SLOTS_PER_EPOCH = 2**5

class WithdrawalSafeBorder:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.lido_contracts = w3.lido_contracts
        self.validators_provider = LidoValidatorsProvider(w3)

    def get_safe_border_epoch(self, blockstamp: BlockStamp):
        is_bunker = self.get_bunker_mode()
        new_request_border_epoch = self.get_new_requests_border_epoch(blockstamp)

        if is_bunker is False:
            return new_request_border_epoch
        
        negative_rebase_border_epoch = self.get_negative_rebase_border_epoch(blockstamp)
        associated_slashings_border_epoch = self.get_associated_slashings_border_epoch(blockstamp)

        return min(
            negative_rebase_border_epoch,
            associated_slashings_border_epoch
        )

    def get_new_requests_border_epoch(self, blockstamp: BlockStamp):
        return get_epoch_by_slot(blockstamp.slot_number) - NEW_REQUESTS_BORDER

    def get_negative_rebase_border_epoch(self, blockstamp: BlockStamp):  
        bunker_start_timestamp = self.get_bunker_mode_start_timestamp()
        bunker_start_epoch = get_epoch_by_timestamp(bunker_start_timestamp)

        bunker_start_border_epoch = bunker_start_epoch - NEW_REQUESTS_BORDER
        earliest_allowable_epoch = get_epoch_by_slot(blockstamp.slot_number) - MAX_NEGATIVE_REBASE_BORDER

        return max(earliest_allowable_epoch, bunker_start_border_epoch)

    def get_associated_slashings_border_epoch(self, blockstamp: BlockStamp):
        earliest_slashed_epoch = self.get_earliest_slashed_epoch_among_incomplete_slashings(blockstamp)

        if earliest_slashed_epoch is None:
            return blockstamp.slot_number
        
        rounded_epoch = get_epoch_by_slot(earliest_slashed_epoch)
        return rounded_epoch - NEW_REQUESTS_BORDER

    def get_earliest_slashed_epoch_among_incomplete_slashings(self, blockstamp: BlockStamp):
        validators = self.validators_provider.get_lido_validators(blockstamp)       
        validators_slashed = filter_slashed_validators(validators)
        validators_slashed_non_withdrawable = filter_non_withdrawable_validators(validators_slashed, blockstamp.slot_number)

        if len(validators_slashed_non_withdrawable) == 0:
            return None

        validators_with_earliest_exit_epoch = self.get_validators_with_earliest_exit_epoch(validators_slashed_non_withdrawable)
        first_validator_with_earliest_exit_epoch = validators_with_earliest_exit_epoch[0]
        earliest_slashed_epoch = self.calc_validator_slashed_epoch_from_state(first_validator_with_earliest_exit_epoch)

        if earliest_slashed_epoch is not None:
            return earliest_slashed_epoch
        
        earliest_slashed_epoch = self.find_earliest_slashed_epoch(validators_with_earliest_exit_epoch, blockstamp.slot_number)
        return earliest_slashed_epoch

    def get_validators_with_earliest_exit_epoch(self, validators):
        if len(validators) == 0:
            return []

        sorted_validators = sorted(validators, key = lambda validator: (int(validator.validator.validator.exit_epoch)))
        earliest_exit_epoch = sorted_validators[0].validator.validator.exit_epoch
        return filter_validators_by_exit_epoch(sorted_validators, earliest_exit_epoch)

    def calc_validator_slashed_epoch_from_state(self, validator):
        """
        Calculates slashed epoch based on current validator state
        Returns None in case it can't be calculated from the state
        """
        exit_epoch = int(validator.validator.validator.exit_epoch)
        withdrawable_epoch = int(validator.validator.validator.withdrawable_epoch)

        exited_period = withdrawable_epoch - exit_epoch
        is_slashed_epoch_undetectable = exited_period > MIN_VALIDATOR_WITHDRAWABILITY_DELAY
        if is_slashed_epoch_undetectable:
            return None

        return withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR

    def find_earliest_slashed_epoch(self, validators, ref_slot):
        """
        Returns the earliest slashed epoch for the validator list, making historical queries 
        to the CL node and tracking slashed flag changes
        """
        pubkeys = get_validators_pubkeys(validators)
        withdrawable_epoch = min(get_validators_withdrawable_epochs(validators))

        start_slot = 0
        end_slot = min(ref_slot, get_epoch_first_slot(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR))

        while start_slot + 1 < end_slot:
            mid_slot = (end_slot + start_slot) // 2
            validators = self.get_archive_lido_validators_by_keys(mid_slot, pubkeys)
            slashed_validators = filter_slashed_validators(validators)

            if len(slashed_validators) > 0:
                end_slot = mid_slot - 1
            else:
                start_slot = mid_slot + 1

        return get_epoch_by_slot(end_slot)

    def get_bunker_mode(self) -> bool:
        return self.lido_contracts.withdrawal_queue.functions.isBunkerModeActive().call()

    def get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        return self.validators_provider.get_lido_validators(blockstamp)

    def get_archive_lido_validators_by_keys(self, slot_number, pubkeys):
        return self.w3.cc.get_validators(slot_number, tuple(pubkeys))

    def get_bunker_mode_start_timestamp(self) -> str:
        return self.w3.lido_contracts.withdrawal_queue.functions.bunkerModeSinceTimestamp().call()

def get_epoch_first_slot(epoch):
    return epoch * SLOTS_PER_EPOCH

def get_epoch_by_slot(slot_number):
    return int(slot_number / SLOTS_PER_EPOCH)

def get_epoch_by_timestamp(timestamp: str):
    return int(timestamp / SLOTS_PER_EPOCH * 12)
                

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