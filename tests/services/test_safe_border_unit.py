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

def create_validator_stub(exit_epoch, withdrawable_epoch):
    validator_state = create_validator_state(exit_epoch, withdrawable_epoch)
    return create_lido_validator(create_validator(validator_state))

def create_validator_state(exit_epoch, withdrawable_epoch) -> ValidatorState:
    return ValidatorState(
        pubkey=None, 
        withdrawal_credentials=None, 
        effective_balance=None,
        activation_eligibility_epoch=None,
        activation_epoch=None,
        slashed=False,
        exit_epoch=exit_epoch,
        withdrawable_epoch=withdrawable_epoch
    )

def create_validator(validator: ValidatorState) -> Validator:
    return Validator(validator=validator, status=None, index=None, balance=None)

def create_lido_validator(validator: Validator) -> LidoValidator:
    return LidoValidator(LidoKey(key=None, depositSignature=None, operatorIndex=None, used=False, moduleAddress=None), validator=validator)
