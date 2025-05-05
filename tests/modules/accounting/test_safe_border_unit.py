from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from src.modules.submodules.consensus import ChainConfig, FrameConfig
from src.providers.consensus.types import ValidatorState
from src.services.safe_border import SafeBorder
from src.web3py.extensions.lido_validators import Validator
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import OracleReportLimitsFactory
from tests.factory.no_registry import ValidatorFactory, ValidatorStateFactory

FAR_FUTURE_EPOCH = 2**64 - 1
MIN_VALIDATOR_WITHDRAWABILITY_DELAY = 2**8
EPOCHS_PER_SLASHINGS_VECTOR = 2**13
SLOTS_PER_EPOCH = 2**5
SLOT_TIME = 12


def create_validator_stub(exit_epoch, withdrawable_epoch, slashed=False):
    return create_validator(create_validator_state(exit_epoch, withdrawable_epoch, slashed))


def create_validator_state(exit_epoch, withdrawable_epoch, slashed) -> ValidatorState:
    return ValidatorStateFactory.build(
        slashed=slashed,
        exit_epoch=exit_epoch,
        withdrawable_epoch=withdrawable_epoch,
    )


def create_validator(validator: ValidatorState) -> Validator:
    return ValidatorFactory.build(validator=validator)


@dataclass(frozen=True)
class WithdrawalStatus:
    timestamp: int


@pytest.fixture()
def chain_config():
    yield ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0)


@pytest.fixture()
def frame_config():
    yield FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture()
def past_blockstamp():
    yield ReferenceBlockStampFactory.build()


@pytest.fixture()
def safe_border(
    chain_config,
    frame_config,
    past_blockstamp,
    web3,
):
    web3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=OracleReportLimitsFactory.build()
    )
    web3.lido_contracts.oracle_daemon_config.finalization_max_negative_rebase_epoch_shift = Mock(return_value=100)
    return SafeBorder(web3, past_blockstamp, chain_config, frame_config)


@pytest.mark.unit
def test_get_new_requests_border_epoch(safe_border, past_blockstamp):
    border = safe_border._get_default_requests_border_epoch()

    assert border == past_blockstamp.ref_slot // SLOTS_PER_EPOCH - safe_border.finalization_default_shift


@pytest.mark.unit
def test_calc_validator_slashed_epoch_from_state(safe_border):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY + 1
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert safe_border._predict_earliest_slashed_epoch(validator) == withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR


@pytest.mark.unit
def test_calc_validator_slashed_epoch_from_state_undetectable(safe_border):
    exit_epoch = 504800
    withdrawable_epoch = exit_epoch + MIN_VALIDATOR_WITHDRAWABILITY_DELAY
    validator = create_validator_stub(exit_epoch, withdrawable_epoch)

    assert safe_border._predict_earliest_slashed_epoch(validator) is None


@pytest.mark.unit
def test_get_negative_rebase_border_epoch(safe_border, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    safe_border._get_bunker_start_or_last_successful_report_epoch = Mock(return_value=ref_epoch)

    assert safe_border._get_negative_rebase_border_epoch() == ref_epoch - safe_border.finalization_default_shift


@pytest.mark.unit
def test_get_negative_rebase_border_epoch_bunker_not_started_yet(safe_border, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    safe_border._get_bunker_start_or_last_successful_report_epoch = Mock(return_value=ref_epoch)

    assert safe_border._get_negative_rebase_border_epoch() == ref_epoch - safe_border.finalization_default_shift


@pytest.mark.unit
def test_get_negative_rebase_border_epoch_max(safe_border, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH
    max_negative_rebase_shift = (
        safe_border.w3.lido_contracts.oracle_daemon_config.finalization_max_negative_rebase_epoch_shift()
    )
    test_epoch = ref_epoch - max_negative_rebase_shift - 1
    safe_border._get_bunker_mode_start_timestamp = Mock(return_value=test_epoch * SLOTS_PER_EPOCH * SLOT_TIME)

    assert safe_border._get_negative_rebase_border_epoch() == ref_epoch - max_negative_rebase_shift


@pytest.mark.unit
def test_get_associated_slashings_border_epoch(safe_border, past_blockstamp):
    ref_epoch = past_blockstamp.ref_slot // SLOTS_PER_EPOCH

    safe_border._get_earliest_slashed_epoch_among_incomplete_slashings = Mock(return_value=None)
    assert safe_border._get_associated_slashings_border_epoch() == ref_epoch - safe_border.finalization_default_shift

    test_epoch = ref_epoch - 100
    safe_border._get_earliest_slashed_epoch_among_incomplete_slashings = Mock(return_value=test_epoch)
    assert (
        safe_border._get_associated_slashings_border_epoch()
        == safe_border.round_epoch_by_frame(test_epoch) - safe_border.finalization_default_shift
    )


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_validators(safe_border, past_blockstamp):
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=[])

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() is None


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_no_slashed_validators(safe_border, past_blockstamp):
    safe_border.w3.lido_validators.get_lido_validators = Mock(
        return_value=[
            create_validator_stub(100, 105),
            create_validator_stub(102, 107),
            create_validator_stub(103, 108),
        ]
    )

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() is None


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_withdrawable_validators(safe_border, past_blockstamp):
    withdrawable_epoch = past_blockstamp.ref_epoch - 10
    validators = [create_validator_stub(100, withdrawable_epoch, True)]
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() is None


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_unable_to_predict(safe_border, past_blockstamp):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY, non_withdrawable_epoch, True
        )
    ]
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=validators)
    safe_border._find_earliest_slashed_epoch_rounded_to_frame = Mock(return_value=1331)

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() == 1331


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_all_withdrawable(safe_border, past_blockstamp):
    validators = [
        create_validator_stub(
            past_blockstamp.ref_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY, past_blockstamp.ref_epoch - 1, True
        ),
        create_validator_stub(
            past_blockstamp.ref_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY, past_blockstamp.ref_epoch - 2, True
        ),
    ]
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() is None


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_predicted(safe_border, past_blockstamp):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY - 1, non_withdrawable_epoch, True
        ),
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY - 2, non_withdrawable_epoch, True
        ),
    ]
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=validators)

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() == (
        non_withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR
    )


@pytest.mark.unit
def test_get_earliest_slashed_epoch_among_incomplete_slashings_at_least_one_unpredictable_epoch(
    safe_border,
    past_blockstamp,
):
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    validators = [
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY, non_withdrawable_epoch + 1, True
        ),
        create_validator_stub(
            non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY, non_withdrawable_epoch, True
        ),
    ]
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=validators)
    safe_border._find_earliest_slashed_epoch_rounded_to_frame = Mock(return_value=1331)

    assert safe_border._get_earliest_slashed_epoch_among_incomplete_slashings() == 1331


###
# Test should ensure that there is no filtering applied to the inputs of _find_earliest_slashed_epoch_rounded_to_frame.
# Previously under some conditions we could trap into situation printed below, because of the exit_epoch filtering.
# validator 1:
# --|-------------|-------|-----|------------->
#   initiate      slashed exit  withdrawable
#   exit          epoch   epoch epoch


# validator 2:
# ------|------------------|---------------|-->
#       slashed            exit            withdrawable
#       epoch              epoch           epoch
#
#     ^
#     expected
#     safe
#     border
###
@pytest.mark.unit
def test_get_earliest_slashed_epcoh_if_exiting_validator_slashed(safe_border, past_blockstamp):
    # in binary search:
    # start frame = 73
    # end frame = 101

    # Assume that validator 1 slashed at 84
    # Assume that validator 2 slashed at 74
    non_withdrawable_epoch = past_blockstamp.ref_epoch + 10
    exit_epoch = non_withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY
    safe_border._get_last_finalized_withdrawal_request_epoch = Mock(return_value=0)

    # predicted_epoch = None
    validator1 = ValidatorFactory.build(
        validator=ValidatorStateFactory.build(
            slashed=True,
            exit_epoch=exit_epoch,
            withdrawable_epoch=non_withdrawable_epoch,
            activation_epoch=exit_epoch - EPOCHS_PER_SLASHINGS_VECTOR - 25,
        )
    )

    validator2 = ValidatorFactory.build(
        validator=ValidatorStateFactory.build(
            slashed=True,
            exit_epoch=exit_epoch + 1,
            withdrawable_epoch=non_withdrawable_epoch + 25,
            activation_epoch=exit_epoch - EPOCHS_PER_SLASHINGS_VECTOR - 300,
        )
    )
    safe_border._slashings_in_frame = Mock(side_effect=lambda frame, slashed_pubkeys: frame >= 45)
    safe_border.w3.lido_validators.get_lido_validators = Mock(return_value=[validator1, validator2])
    earliest_slashed_epoch = safe_border._get_earliest_slashed_epoch_among_incomplete_slashings()
    assert earliest_slashed_epoch == 450


@pytest.mark.unit
def test_get_bunker_start_or_last_successful_report_epoch_no_bunker_start(safe_border, past_blockstamp):
    safe_border._get_bunker_mode_start_timestamp = Mock(return_value=None)
    safe_border.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(return_value=past_blockstamp.ref_slot)

    assert safe_border._get_bunker_start_or_last_successful_report_epoch() == past_blockstamp.ref_slot // 32


@pytest.mark.unit
def test_get_bunker_start_or_last_successful_report_epoch(safe_border, past_blockstamp):
    safe_border._get_bunker_mode_start_timestamp = Mock(return_value=past_blockstamp.ref_slot * 12)

    assert safe_border._get_bunker_start_or_last_successful_report_epoch() == past_blockstamp.ref_slot // 32


@pytest.mark.unit
def test_get_last_finalized_withdrawal_request_epoch(safe_border):
    timestamp = 1677230000

    safe_border.w3.lido_contracts.withdrawal_queue_nft.get_last_finalized_request_id = Mock(return_value=3)
    safe_border.w3.lido_contracts.withdrawal_queue_nft.get_withdrawal_status = Mock(
        return_value=WithdrawalStatus(timestamp=timestamp)
    )

    slot = (timestamp - safe_border.chain_config.genesis_time) // safe_border.chain_config.seconds_per_slot
    epoch = slot // safe_border.chain_config.slots_per_epoch

    assert safe_border._get_last_finalized_withdrawal_request_epoch() == epoch


@pytest.mark.unit
def test_get_last_finalized_withdrawal_request_epoch_no_requests(safe_border):
    safe_border.w3.lido_contracts.withdrawal_queue_nft.get_last_finalized_request_id = Mock(return_value=0)

    assert safe_border._get_last_finalized_withdrawal_request_epoch() == 0
