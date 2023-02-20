from src.web3py.typings import Web3
from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import LidoValidator
from src.modules.submodules.consensus import ChainConfig

DEFAULT_SHIFT = 8 # epochs ~50 min
MAX_NEGATIVE_REBASE_SHIFT = 1536 # epochs ~6.8 days
FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13

class SafeBorder:
    def __init__(self, w3: Web3) -> None:
        self.w3 = w3
        self.lido_contracts = w3.lido_contracts

    def get_safe_border_epoch(self, is_bunker: bool, blockstamp: BlockStamp, chain_config: ChainConfig):
        if not is_bunker:
            return self._get_new_requests_border_epoch(blockstamp)

        self.chain_config = chain_config
        
        negative_rebase_border_epoch = self._get_negative_rebase_border_epoch(blockstamp)
        associated_slashings_border_epoch = self._get_associated_slashings_border_epoch(blockstamp)

        return min(
            negative_rebase_border_epoch,
            associated_slashings_border_epoch
        )

    def _get_new_requests_border_epoch(self, blockstamp: BlockStamp):
        return self.get_epoch_by_slot(blockstamp.ref_slot) - DEFAULT_SHIFT

    def _get_negative_rebase_border_epoch(self, blockstamp: BlockStamp):  
        bunker_start_timestamp = self._get_bunker_mode_start_timestamp(blockstamp)
        bunker_start_epoch = self.get_epoch_by_timestamp(bunker_start_timestamp)

        bunker_start_border_epoch = bunker_start_epoch - DEFAULT_SHIFT
        earliest_allowable_epoch = self.get_epoch_by_slot(blockstamp.ref_slot) - MAX_NEGATIVE_REBASE_SHIFT

        return max(earliest_allowable_epoch, bunker_start_border_epoch)

    def _get_associated_slashings_border_epoch(self, blockstamp: BlockStamp):
        earliest_slashed_epoch = self._get_earliest_slashed_epoch_among_incomplete_slashings(blockstamp)

        if earliest_slashed_epoch is None:
            return self.get_epoch_by_slot(blockstamp.ref_slot) - DEFAULT_SHIFT
        
        return earliest_slashed_epoch - DEFAULT_SHIFT

    def _get_earliest_slashed_epoch_among_incomplete_slashings(self, blockstamp: BlockStamp):
        validators = self._get_lido_validators(blockstamp)       
        validators_slashed = filter_slashed_validators(validators)

        # Here we filter not by exit_epoch but by withdrawable_epoch because exited operators can still be slashed.
        # See more here https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#helpers
        # at `get_eligible_validator_indices` method.
        validators_slashed_non_withdrawable = filter_non_withdrawable_validators(validators_slashed, blockstamp.ref_slot)

        if len(validators_slashed_non_withdrawable) == 0:
            return None

        validators_with_earliest_exit_epoch = self._filter_validators_with_earliest_exit_epoch(validators_slashed_non_withdrawable)
        earliest_slashed_epoch_predicted = self._predict_earliest_slashed_epoch(validators_with_earliest_exit_epoch[0])

        if earliest_slashed_epoch_predicted:
            return earliest_slashed_epoch_predicted
        return self._find_earliest_slashed_epoch(validators_with_earliest_exit_epoch, blockstamp)

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

    def _find_earliest_slashed_epoch(self, validators, blockstamp: BlockStamp):
        pubkeys = get_validators_pubkeys(validators)
        withdrawable_epoch = min(get_validators_withdrawable_epochs(validators))

        last_finalized_request_id_slot = self._get_last_finalized_withdrawal_request_slot(blockstamp)

        start_slot = max(last_finalized_request_id_slot, self._get_validators_earliest_activation_epoch(validators))
        end_slot = min(blockstamp.ref_slot, self.get_epoch_first_slot(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR))

        while start_slot + 1 < end_slot:
            mid_slot = (end_slot + start_slot) // 2
            validators = self._get_archive_lido_validators_by_keys(mid_slot, pubkeys)
            slashed_validators = filter_slashed_validators(validators)

            if len(slashed_validators) > 0:
                end_slot = mid_slot - 1
            else:
                start_slot = mid_slot + 1

        return self.get_epoch_by_slot(end_slot)

    def _filter_validators_with_earliest_exit_epoch(self, validators):
        if len(validators) == 0:
            return []

        sorted_validators = sorted(validators, key = lambda validator: (int(validator.validator.validator.exit_epoch)))
        earliest_exit_epoch = sorted_validators[0].validator.validator.exit_epoch
        return filter_validators_by_exit_epoch(sorted_validators, earliest_exit_epoch)

    def _get_validators_earliest_activation_epoch(self, validators):
        if len(validators) == 0:
            return 0

        sorted_validators = sorted(validators, key = lambda validator: (int(validator.validator.validator.activation_epoch)))
        return sorted_validators[0].validator.validator.activation_epoch

    def _get_lido_validators(self, blockstamp: BlockStamp) -> list[LidoValidator]:
        return self.w3.cc.get_validators(blockstamp.ref_slot)

    def _get_archive_lido_validators_by_keys(self, ref_slot, pubkeys):
        return self.w3.cc.get_validators(ref_slot, tuple(pubkeys))

    def _get_bunker_mode_start_timestamp(self, blockstamp: BlockStamp) -> str:
        return self.w3.lido_contracts.withdrawal_queue.functions.bunkerModeSinceTimestamp().call(block_identifier=blockstamp.block_hash)

    def _get_last_finalized_withdrawal_request_slot(self, blockstamp: BlockStamp) -> int:
        last_finalized_request_id = self.w3.lido_contracts.withdrawal_queue.functions.getLastFinalizedRequestId().call(block_identifier=blockstamp.block_hash)
        last_finalized_request_data = self.w3.lido_contracts.withdrawal_queue.functions.getWithdrawalRequestStatus(last_finalized_request_id).call(block_identifier=blockstamp.block_hash)

        return self.get_epoch_first_slot(self.get_epoch_by_timestamp(last_finalized_request_data.timestamp))

    def get_epoch_first_slot(self, epoch: int):
        return epoch * self.chain_config.slots_per_epoch

    def get_epoch_by_slot(self, ref_slot: int):
        return ref_slot // self.chain_config.slots_per_epoch

    def get_epoch_by_timestamp(self, timestamp: int):
        return (timestamp - self.chain_config.genesis_time) // (self.chain_config.slots_per_epoch * self.chain_config.seconds_per_slot)
                

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