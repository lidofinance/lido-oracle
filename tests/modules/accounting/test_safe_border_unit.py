import pytest
from dataclasses import dataclass

from unittest.mock import Mock
from src.services.safe_border import SafeBorder
from src.web3py.extensions.lido_validators import Validator
from src.providers.consensus.typings import ValidatorState
from src.modules.submodules.consensus import ChainConfig, FrameConfig
from tests.conftest import get_blockstamp_by_state

FAR_FUTURE_EPOCH = 2 ** 64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2 ** 8
EPOCHS_PER_SLASHINGS_VECTOR = 2 ** 13
SLOTS_PER_EPOCH = 2 ** 5
SLOT_TIME = 12


@dataclass(frozen=True)
class WithdrawalStatus:
    timestamp: int


@pytest.fixture()
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.fixture()
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture()
def subject(
    chain_config,
    frame_config,
    past_blockstamp,
    web3,
    contracts,
    keys_api_client,
    consensus_client,
    lido_validators
):
    return SafeBorder(web3, past_blockstamp, chain_config, frame_config)

@pytest.fixture()
def past_blockstamp(web3, consensus_client):
    return get_blockstamp_by_state(web3, 'finalized')


def test_get_new_requests_border_epoch(subject, past_blockstamp):
    assert subject._get_default_requests_border_epoch() == past_blockstamp.ref_slot // (
            SLOTS_PER_EPOCH - subject.finalization_default_shift
    )


def test_calc_validator_slashed_epoch_from_state(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY + 1
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert subject._predict_earliest_slashed_epoch(validator) == withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR


def test_calc_validator_slashed_epoch_from_state_undetectable(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert subject._predict_earliest_slashed_epoch(validator) is None


def test_filter_validators_with_earliest_exit_epoch(subject):
    validators = [
        create_validator_stub(100, 105),
        create_validator_stub(102, 107),
        create_validator_stub(103, 108),
    ]

    assert subject._filter_validators_with_earliest_exit_epoch(validators) == [validators[0]]


def test_get_negative_rebase_border_epoch(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    subject._get_bunker_start_or_last_successful_report_epoch = Mock(return_value=ref_epoch)

    assert subject._get_negative_rebase_border_epoch() == ref_epoch - subject.finalization_default_shift


def test_get_negative_rebase_border_epoch_bunker_not_started_yet(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    subject._get_bunker_start_or_last_successful_report_epoch = Mock(return_value=ref_epoch)

    assert subject._get_negative_rebase_border_epoch() == ref_epoch - subject.finalization_default_shift


def test_get_negative_rebase_border_epoch_max(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    test_epoch = ref_epoch - subject.finalization_max_negative_rebase_shift - 1
    subject._get_bunker_mode_start_timestamp = Mock(return_value=test_epoch * SLOTS_PER_EPOCH * SLOT_TIME)

    assert subject._get_negative_rebase_border_epoch() == ref_epoch - subject.finalization_max_negative_rebase_shift


def test_get_associated_slashings_border_epoch(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH

    subject._get_earliest_slashed_epoch_among_incomplete_slashings = Mock(return_value=None)
    assert subject._get_associated_slashings_border_epoch() == ref_epoch - subject.finalization_default_shift

    test_epoch = ref_epoch - 100
    subject._get_earliest_slashed_epoch_among_incomplete_slashings = Mock(return_value=test_epoch)
    assert subject._get_associated_slashings_border_epoch() == subject.round_epoch_by_frame(
        test_epoch) - subject.finalization_default_shift


def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_validators(subject, past_blockstamp):
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=[])

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_slashed_validators(subject, past_blockstamp):
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=[
        create_validator_stub(100, 105),
        create_validator_stub(102, 107),
        create_validator_stub(103, 108),
    ])

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


def test_get_earliest_slashed_epoch_among_incomplete_slashings_withdrawable_validators(subject, past_blockstamp,
                                                                                       lido_validators):
    withdrawable_epoch = past_blockstamp.ref_epoch - 10
    validators = [
        create_validator_stub(100, withdrawable_epoch, True)
    ]
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


def test_get_earliest_slashed_epoch_among_incomplete_slashings_unable_to_predict(subject, past_blockstamp, lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
            non_withdrawable_epoch,
            True
        )
    ]
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=validators)
    subject._find_earliest_slashed_epoch_rounded_to_frame = Mock(return_value=1331)
    
    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == 1331


def test_get_earliest_slashed_epoch_among_incomplete_slashings_all_withdrawable(subject, past_blockstamp, lido_validators):
    validators = [
        create_validator_stub(
            past_blockstamp.ref_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
            past_blockstamp.ref_epoch - 1,
            True
        ),
        create_validator_stub(
            past_blockstamp.ref_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
            past_blockstamp.ref_epoch - 2,
            True
        ),
    ]
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


def test_get_earliest_slashed_epoch_among_incomplete_slashings_predicted(subject, past_blockstamp, lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY - 1,
            non_withdrawable_epoch,
            True
        ),
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY - 2,
            non_withdrawable_epoch,
            True
        ),
    ]
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == (
            non_withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR
    )

def test_get_earliest_slashed_epoch_among_incomplete_slashings_at_least_one_unpredictable_epoch(subject, past_blockstamp,
                                                                                                lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
            non_withdrawable_epoch + 1,
            True
        ),
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY,
            non_withdrawable_epoch,
            True
        ),
    ]
    subject.w3.lido_validators.get_lido_validators = Mock(return_value=validators)
    subject._find_earliest_slashed_epoch_rounded_to_frame = Mock(return_value=1331)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == 1331


def test_get_bunker_start_or_last_successful_report_epoch_no_bunker_start(subject, past_blockstamp):
    subject._get_bunker_mode_start_timestamp = Mock(return_value=None)
    subject.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=past_blockstamp.ref_slot)

    assert subject._get_bunker_start_or_last_successful_report_epoch() == past_blockstamp.ref_slot // 32


def test_get_bunker_start_or_last_successful_report_epoch(subject, past_blockstamp):
    subject._get_bunker_mode_start_timestamp = Mock(return_value=past_blockstamp.ref_slot * 12)

    assert subject._get_bunker_start_or_last_successful_report_epoch() == past_blockstamp.ref_slot // 32


def test_get_last_finalized_withdrawal_request_slot(subject):
    timestamp = 1677230000
    subject._get_last_finalized_request_id = Mock(return_value=3)
    subject._get_withdrawal_request_status = Mock(return_value=WithdrawalStatus(timestamp=timestamp))

    slot = (timestamp - subject.chain_config.genesis_time) // subject.chain_config.seconds_per_slot
    epoch = slot // subject.chain_config.slots_per_epoch
    first_slot = epoch * subject.chain_config.slots_per_epoch

    assert subject._get_last_finalized_withdrawal_request_slot() == first_slot


def test_get_last_finalized_withdrawal_request_slot_no_requests(subject):
    subject._get_last_finalized_request_id = Mock(return_value=0)

    assert subject._get_last_finalized_withdrawal_request_slot() == 0

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
