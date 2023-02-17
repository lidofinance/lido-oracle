import pytest

from unittest.mock import MagicMock
from src.typings import BlockStamp
from src.services.safe_border import SafeBorder
from src.web3_extentions.lido_validators import LidoValidator, Validator
from src.providers.consensus.typings import ValidatorState

NEW_REQUESTS_BORDER = 8 # epochs ~50 min
MAX_NEGATIVE_REBASE_BORDER = 1536 # epochs ~6.8 days
FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
SLOTS_PER_EPOCH = 2**5
SLOT_TIME = 12

@pytest.fixture()
def ref_blockstamp():
    return BlockStamp(
        block_root=None, 
        state_root=None, 
        slot_number=1000000, 
        block_hash=None,
        block_number=None
    )

@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return SafeBorder(web3)

def test_get_new_requests_border_epoch(subject, ref_blockstamp):
    assert subject.get_new_requests_border_epoch(ref_blockstamp) == ref_blockstamp.slot_number // SLOTS_PER_EPOCH - NEW_REQUESTS_BORDER

def test_calc_validator_slashed_epoch_from_state(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 250
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)
    
    assert subject.calc_validator_slashed_epoch_from_state(validator) == withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR

def test_calc_validator_slashed_epoch_from_state_undetectable(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 1000
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert subject.calc_validator_slashed_epoch_from_state(validator) == None

def test_get_validators_with_earliest_exit_epoch(subject):
    validators = [
        create_validator_stub(100, 105),
        create_validator_stub(102, 107),
        create_validator_stub(103, 108),
    ]

    assert subject.get_validators_with_earliest_exit_epoch(validators) == [validators[0]]
    assert subject.get_validators_with_earliest_exit_epoch([]) == []

def test_get_negative_rebase_border_epoch(subject, ref_blockstamp):
    ref_epoch = ref_blockstamp.slot_number // SLOTS_PER_EPOCH
    subject.get_bunker_mode_start_timestamp = MagicMock(return_value=ref_epoch * SLOTS_PER_EPOCH * SLOT_TIME)
    
    assert subject.get_negative_rebase_border_epoch(ref_blockstamp) == ref_epoch - NEW_REQUESTS_BORDER

def test_get_negative_rebase_border_epoch_max(subject, ref_blockstamp):
    ref_epoch = ref_blockstamp.slot_number // SLOTS_PER_EPOCH
    test_epoch = ref_epoch - MAX_NEGATIVE_REBASE_BORDER - 1
    subject.get_bunker_mode_start_timestamp = MagicMock(return_value=test_epoch * SLOTS_PER_EPOCH * SLOT_TIME)
    
    assert subject.get_negative_rebase_border_epoch(ref_blockstamp) == ref_epoch - MAX_NEGATIVE_REBASE_BORDER

def test_get_associated_slashings_border_epoch(subject, ref_blockstamp):
    ref_epoch = ref_blockstamp.slot_number // SLOTS_PER_EPOCH

    subject.get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=None)
    assert subject.get_associated_slashings_border_epoch(ref_blockstamp) == ref_epoch - NEW_REQUESTS_BORDER

    test_epoch = ref_epoch - 100
    subject.get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=test_epoch)
    assert subject.get_associated_slashings_border_epoch(ref_blockstamp) == test_epoch - NEW_REQUESTS_BORDER

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
    return LidoValidator(key=None, validator=validator)
