import pytest
from dataclasses import dataclass

from unittest.mock import MagicMock, Mock
from src.typings import ReferenceBlockStamp
from src.services.safe_border import SafeBorder
from src.web3py.extentions.lido_validators import Validator
from src.providers.consensus.typings import ValidatorState
from src.modules.submodules.consensus import ChainConfig, FrameConfig


NEW_REQUESTS_BORDER = 8  # epochs ~50 min
MAX_NEGATIVE_REBASE_BORDER = 1536  # epochs ~6.8 days
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
def subject(chain_config, frame_config, past_blockstamp, contracts, keys_api_client, consensus_client):
    web3 = Mock()
    safe_border = SafeBorder(web3, past_blockstamp, chain_config, frame_config)
    safe_border._retrieve_constants = Mock()
    safe_border.finalization_default_shift = NEW_REQUESTS_BORDER
    safe_border.finalization_max_negative_rebase_shift = MAX_NEGATIVE_REBASE_BORDER
    return safe_border

@pytest.fixture()
def past_blockstamp():
    yield ReferenceBlockStamp(
        ref_slot=4947936,
        ref_epoch=154623,
        block_root='0xfc3a63409fe5c53c3bb06a96fc4caa89011452835f767e64bf59f2b6864037cc',
        state_root='0x7fcd917cbe34f306989c40bd64b8e2057a39dfbfda82025549f3a44e6b2295fc',
        slot_number=4947936,
        block_number=8457825,
        block_hash='0x0d61eeb26e4cbb076e557ddb8de092a05e2cba7d251ad4a87b0826cf5926f87b',
        block_timestamp=0
    )

def test_get_new_requests_border_epoch(subject, past_blockstamp):
    assert subject._get_default_requests_border_epoch() == past_blockstamp.ref_slot // SLOTS_PER_EPOCH - NEW_REQUESTS_BORDER


def test_calc_validator_slashed_epoch_from_state(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 250
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert subject._predict_earliest_slashed_epoch(validator) == withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR


def test_calc_validator_slashed_epoch_from_state_undetectable(subject):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + 1000
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
    subject._get_bunker_start_or_last_successful_report_epoch = MagicMock(return_value=ref_epoch)

    assert subject._get_negative_rebase_border_epoch() == ref_epoch - NEW_REQUESTS_BORDER


def test_get_negative_rebase_border_epoch_bunker_not_started_yet(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    subject._get_bunker_start_or_last_successful_report_epoch = MagicMock(return_value=ref_epoch)

    assert subject._get_negative_rebase_border_epoch() == ref_epoch - NEW_REQUESTS_BORDER


def test_get_negative_rebase_border_epoch_max(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    test_epoch = ref_epoch - MAX_NEGATIVE_REBASE_BORDER - 1
    subject._get_bunker_mode_start_timestamp = MagicMock(return_value=test_epoch * SLOTS_PER_EPOCH * SLOT_TIME)

    assert subject._get_negative_rebase_border_epoch() == ref_epoch - MAX_NEGATIVE_REBASE_BORDER


def test_get_associated_slashings_border_epoch(subject, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH

    subject._get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=None)
    assert subject._get_associated_slashings_border_epoch() == ref_epoch - NEW_REQUESTS_BORDER

    test_epoch = ref_epoch - 100
    subject._get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=test_epoch)
    assert subject._get_associated_slashings_border_epoch() == subject.round_epoch_by_frame(
        test_epoch) - NEW_REQUESTS_BORDER


def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_validators(subject, past_blockstamp):
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=[])

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_slashed_validators(subject, past_blockstamp):
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=[
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
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


@pytest.mark.skip
def test_get_earliest_slashed_epoch_among_incomplete_slashings_unable_to_predict(subject, past_blockstamp, lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY - 1, non_withdrawable_epoch,
                              True)
    ]
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=validators)
    subject._find_latest_non_slashed_epoch = MagicMock(return_value=1331)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == 1331


def test_get_earliest_slashed_epoch_among_incomplete_slashings_all_withdrawable(subject, past_blockstamp, lido_validators):
    validators = [
        create_validator_stub(past_blockstamp.ref_epoch - 100, past_blockstamp.ref_epoch - 1, True),
        create_validator_stub(past_blockstamp.ref_epoch - 100, past_blockstamp.ref_epoch - 2, True),
    ]
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() is None


@pytest.mark.skip
def test_get_earliest_slashed_epoch_among_incomplete_slashings_predicted(subject, past_blockstamp, lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(non_withdrawable_epoch - 100, non_withdrawable_epoch, True),
        create_validator_stub(non_withdrawable_epoch - 100, non_withdrawable_epoch + 1, True),
    ]
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == non_withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR


@pytest.mark.skip
def test_get_earliest_slashed_epoch_among_incomplete_slashings_predicted_different_exit_epoch(subject, past_blockstamp,
                                                                                              lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(non_withdrawable_epoch - 100, non_withdrawable_epoch, True),
        create_validator_stub(non_withdrawable_epoch - 100, non_withdrawable_epoch + 1, True),
    ]
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=validators)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == non_withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR


@pytest.mark.skip
def test_get_earliest_slashed_epoch_among_incomplete_slashings_at_least_one_unpredictable_epoch(subject, past_blockstamp,
                                                                                                lido_validators):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(non_withdrawable_epoch - 100,
                              non_withdrawable_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY, True),
        create_validator_stub(non_withdrawable_epoch - 100, non_withdrawable_epoch + 1, True),
    ]
    subject.w3.lido_validators.get_lido_validators = MagicMock(return_value=validators)
    subject._find_latest_non_slashed_epoch = MagicMock(return_value=1331)

    assert subject._get_earliest_slashed_epoch_among_incomplete_slashings() == 1331


def test_get_bunker_start_or_last_successful_report_epoch_no_bunker_start(subject, past_blockstamp):
    subject._get_bunker_mode_start_timestamp = MagicMock(return_value=None)
    subject._get_last_successful_report_slot = MagicMock(return_value=past_blockstamp.ref_slot)

    assert subject._get_bunker_start_or_last_successful_report_epoch() == past_blockstamp.ref_slot // 32


def test_get_bunker_start_or_last_successful_report_epoch(subject, past_blockstamp):
    subject._get_bunker_mode_start_timestamp = MagicMock(return_value=past_blockstamp.ref_slot * 12)

    assert subject._get_bunker_start_or_last_successful_report_epoch() == past_blockstamp.ref_slot // 32


def test_get_last_finalized_withdrawal_request_slot(subject):
    timestamp = 1677230000
    subject._get_last_finalized_request_id = MagicMock(return_value=3)
    subject._get_withdrawal_request_status = MagicMock(return_value=WithdrawalStatus(timestamp=timestamp))

    slot = (timestamp - subject.chain_config.genesis_time) // subject.chain_config.seconds_per_slot
    epoch = slot // subject.chain_config.slots_per_epoch
    first_slot = epoch * subject.chain_config.slots_per_epoch

    assert subject._get_last_finalized_withdrawal_request_slot() == first_slot


def test_get_last_finalized_withdrawal_request_slot_no_requests(subject):
    subject._get_last_finalized_request_id = MagicMock(return_value=0)

    assert subject._get_last_finalized_withdrawal_request_slot() == 0


def test_check_slots_in_one_frame(subject):
    slot_a = 1
    slot_b = 319
    slot_c = 320

    assert subject._check_slots_in_one_frame_or_close_than_in_one_epoch(slot_a, slot_b)
    assert subject._check_slots_in_one_frame_or_close_than_in_one_epoch(slot_b, slot_c)
    assert not subject._check_slots_in_one_frame_or_close_than_in_one_epoch(slot_a, slot_c)


def create_validator_stub(exit_epoch, withdrawable_epoch, slashed=False):
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
