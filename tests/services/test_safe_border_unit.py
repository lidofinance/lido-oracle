import pytest

from unittest.mock import MagicMock, Mock, patch
from src.services.safe_border import SafeBorder
from src.web3py.extentions.lido_validators import LidoValidator, Validator, LidoKey
from src.providers.consensus.typings import ValidatorState
from src.modules.submodules.consensus import ChainConfig

NEW_REQUESTS_BORDER = 8 # epochs ~50 min
MAX_NEGATIVE_REBASE_BORDER = 1536 # epochs ~6.8 days
FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
SLOTS_PER_EPOCH = 2**5
SLOT_TIME = 12

@pytest.fixture()
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)

@pytest.fixture()
def subject(web3, chain_config, contracts, keys_api_client, consensus_client):
    safe_border = SafeBorder(web3)
    safe_border.chain_config = chain_config
    return safe_border

def test_get_new_requests_border_epoch(subject, past_blockstamp):
    assert subject._get_new_requests_border_epoch(past_blockstamp) == past_blockstamp.ref_slot // SLOTS_PER_EPOCH - NEW_REQUESTS_BORDER

def test_calc_validator_slashed_epoch_from_state(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 250
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)
    
    assert subject._predict_earliest_slashed_epoch(validator) == withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR

def test_calc_validator_slashed_epoch_from_state_undetectable(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 1000
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert subject._predict_earliest_slashed_epoch(validator) == None

def test_filter_validators_with_earliest_exit_epoch(subject):
    validators = [
        create_validator_stub(100, 105),
        create_validator_stub(102, 107),
        create_validator_stub(103, 108),
    ]

    assert subject._filter_validators_with_earliest_exit_epoch(validators) == [validators[0]]
    assert subject._filter_validators_with_earliest_exit_epoch([]) == []

def test_get_negative_rebase_border_epoch(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    subject._get_bunker_mode_start_timestamp = MagicMock(return_value=ref_epoch * SLOTS_PER_EPOCH * SLOT_TIME)
    
    assert subject._get_negative_rebase_border_epoch(past_blockstamp) == ref_epoch - NEW_REQUESTS_BORDER

def test_get_negative_rebase_border_epoch_bunker_not_started_yet(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    subject._get_bunker_mode_start_timestamp = MagicMock(return_value=(ref_epoch * SLOTS_PER_EPOCH * SLOT_TIME) * 2)
    subject._get_last_successful_report_slot = MagicMock(return_value=(past_blockstamp.ref_slot - 32))
    
    assert subject._get_negative_rebase_border_epoch(past_blockstamp) == ref_epoch - NEW_REQUESTS_BORDER - 1

def test_get_negative_rebase_border_epoch_max(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    test_epoch = ref_epoch - MAX_NEGATIVE_REBASE_BORDER - 1
    subject._get_bunker_mode_start_timestamp = MagicMock(return_value=test_epoch * SLOTS_PER_EPOCH * SLOT_TIME)
    
    assert subject._get_negative_rebase_border_epoch(past_blockstamp) == ref_epoch - MAX_NEGATIVE_REBASE_BORDER

def test_get_associated_slashings_border_epoch(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH

    subject._get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=None)
    assert subject._get_associated_slashings_border_epoch(past_blockstamp) == ref_epoch - NEW_REQUESTS_BORDER

    test_epoch = ref_epoch - 100
    subject._get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=test_epoch)
    assert subject._get_associated_slashings_border_epoch(past_blockstamp) == test_epoch - NEW_REQUESTS_BORDER

def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_validators(subject, past_blockstamp):
    subject._get_lido_validators = MagicMock(return_value=[])

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings(past_blockstamp) == None

def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_slashed_validators(subject, past_blockstamp):
    subject._get_lido_validators = MagicMock(return_value=[
        create_validator_stub(100, 105),
        create_validator_stub(102, 107),
        create_validator_stub(103, 108),
    ])
    
    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings(past_blockstamp) == None

def test_get_earliest_slashed_epoch_among_incomplete_slashings_withdrawable_validators(subject, past_blockstamp):
    withdrawable_slot = past_blockstamp.ref_slot - 10
    validators = [
        create_validator_stub(100, withdrawable_slot, True)
    ]
    subject._get_lido_validators = MagicMock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings(past_blockstamp) == None

def test_get_earliest_slashed_epoch_among_incomplete_slashings_unable_to_predict(subject, past_blockstamp):
    non_withdrawable_slot = past_blockstamp.ref_slot + 10
    validators = [
        create_validator_stub(non_withdrawable_slot - MIN_VALIDATOR_WITHDRAWABILITY_DELAY - 1, non_withdrawable_slot, True)
    ]
    subject._get_lido_validators = MagicMock(return_value=validators)
    subject._find_earliest_slashed_epoch = MagicMock(return_value=1331)
    
    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings(past_blockstamp) == 1331

def test_get_earliest_slashed_epoch_among_incomplete_slashings_predicted(subject, past_blockstamp):
    non_withdrawable_slot = past_blockstamp.ref_slot + 10
    validators = [
        create_validator_stub(non_withdrawable_slot - 100, non_withdrawable_slot, True),
        create_validator_stub(non_withdrawable_slot - 100, non_withdrawable_slot + 1, True),
    ]
    subject._get_lido_validators = MagicMock(return_value=validators)
    subject._find_earliest_slashed_epoch = MagicMock(return_value=1331)
    
    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings(past_blockstamp) == non_withdrawable_slot - EPOCHS_PER_SLASHINGS_VECTOR

def test_get_earliest_slashed_epoch_among_incomplete_slashings_predicted_different_exit_epoch(subject, past_blockstamp):
    non_withdrawable_slot = past_blockstamp.ref_slot + 10
    validators = [
        create_validator_stub(non_withdrawable_slot - 100, non_withdrawable_slot, True),
        create_validator_stub(non_withdrawable_slot - 100, non_withdrawable_slot + 1, True),
    ]
    subject._get_lido_validators = MagicMock(return_value=validators)
    subject._find_earliest_slashed_epoch = MagicMock(return_value=1331)
    
    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings(past_blockstamp) == non_withdrawable_slot - EPOCHS_PER_SLASHINGS_VECTOR

def create_validator_stub(exit_epoch, withdrawable_epoch, slashed = False):
    return create_validator(create_validator_state(exit_epoch, withdrawable_epoch, slashed))

def create_validator_state(exit_epoch, withdrawable_epoch, slashed) -> ValidatorState:
    return ValidatorState(
        pubkey=None, 
        withdrawal_credentials=None, 
        effective_balance=None,
        activation_eligibility_epoch=None,
        activation_epoch=None,
        slashed=slashed,
        exit_epoch=exit_epoch,
        withdrawable_epoch=withdrawable_epoch
    )

def create_validator(validator: ValidatorState) -> Validator:
    return Validator(validator=validator, status=None, index=None, balance=None)
