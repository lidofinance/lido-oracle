import pytest
from unittest.mock import MagicMock

from src.services.withdrawal_safe_border import WithdrawalSafeBorder
from src.web3_extentions.lido_validators import LidoValidator, Validator
from src.providers.consensus.typings import ValidatorState


@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return WithdrawalSafeBorder(web3)

def test_no_bunker_mode(subject, past_blockstamp):
    assert subject.get_safe_border_epoch(past_blockstamp) == int(past_blockstamp.slot_number / 32) - 8

def test_bunker_mode_associated_slashing(subject, past_blockstamp):
    subject.get_bunker_mode = MagicMock(return_value=True)
    # ref_epoch = int(past_blockstamp.slot_number / 32)
    subject.get_safe_border_epoch(past_blockstamp)

def test_bunker_mode_negative_rebase(subject, past_blockstamp):
    pass

def test_calc_validator_slashed_epoch_from_state(subject):
    validator = create_validator_stub(504800, 505050)
    withdrawable_epoch = validator.validator.validator.withdrawable_epoch
    
    assert subject.calc_validator_slashed_epoch_from_state(validator) == withdrawable_epoch - 2**13

def test_calc_validator_slashed_epoch_from_state(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 250
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)
    
    assert subject.calc_validator_slashed_epoch_from_state(validator) == withdrawable_epoch - 2**13

def test_calc_validator_slashed_epoch_from_state_undetectable(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 1000
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert subject.calc_validator_slashed_epoch_from_state(validator) == None


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
