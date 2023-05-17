import pytest
from unittest.mock import MagicMock
from src.services.safe_border import SafeBorder
from tests.factory.no_registry import ValidatorFactory


@pytest.mark.unit
@pytest.mark.parametrize(
    "is_bunker, negative_rebase_border_epoch, associated_slashings_border_epoch, default_requests_border_epoch, expected",
    [
        (True, 1, 2, 7, 1),
        (True, 20, 5, 7, 5),
        (False, 20, 5, 7, 7),
    ],
)
def test_get_safe_border_epoch(
    is_bunker,
    negative_rebase_border_epoch,
    associated_slashings_border_epoch,
    default_requests_border_epoch,
    expected,
):
    SafeBorder._retrieve_constants = MagicMock
    SafeBorder._get_negative_rebase_border_epoch = MagicMock(return_value=negative_rebase_border_epoch)
    SafeBorder._get_associated_slashings_border_epoch = MagicMock(return_value=associated_slashings_border_epoch)
    SafeBorder._get_default_requests_border_epoch = MagicMock(return_value=default_requests_border_epoch)

    web3Mock = MagicMock
    web3Mock.lido_contracts = MagicMock

    sb = SafeBorder(w3=web3Mock, blockstamp=MagicMock, chain_config=MagicMock, frame_config=MagicMock)

    actual = sb.get_safe_border_epoch(is_bunker=is_bunker)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "get_bunker_timestamp, slots_per_epoch, last_processing_ref_slot, initial_epoch, expected",
    [
        (None, 12, 12, 1251, 1),
        (None, 12, 0, 1251, 1251),
    ],
)
def test_get_bunker_start_or_last_successful_report_epoch(
    get_bunker_timestamp, slots_per_epoch, last_processing_ref_slot, initial_epoch, expected
):
    SafeBorder._retrieve_constants = MagicMock
    SafeBorder._get_negative_rebase_border_epoch = MagicMock()
    SafeBorder._get_associated_slashings_border_epoch = MagicMock()
    SafeBorder._get_default_requests_border_epoch = MagicMock()
    SafeBorder._get_bunker_mode_start_timestamp = MagicMock(return_value=get_bunker_timestamp)
    web3Mock = MagicMock()
    web3Mock.lido_contracts.get_accounting_last_processing_ref_slot = MagicMock(return_value=last_processing_ref_slot)

    chain_config = MagicMock
    chain_config.slots_per_epoch = slots_per_epoch
    chain_config.initial_epoch = initial_epoch

    sb = SafeBorder(w3=web3Mock, blockstamp=MagicMock, chain_config=chain_config, frame_config=MagicMock)

    actual = sb._get_bunker_start_or_last_successful_report_epoch()

    assert expected == actual


@pytest.fixture
def validators():
    validators = ValidatorFactory.batch(2)

    validators[0].validator.activation_epoch = "90"
    validators[0].validator.pubkey = "pubkey_validator_1"
    validators[0].validator.withdrawable_epoch = "8292"
    validators[0].validator.slashed = True

    validators[1].validator.activation_epoch = "90"
    validators[1].validator.pubkey = "pubkey_validator_2"
    validators[1].validator.withdrawable_epoch = "8292"
    validators[1].validator.slashed = False

    return validators


@pytest.fixture
def frame_config():
    frame_config = MagicMock
    frame_config.initial_epoch = 50
    frame_config.epochs_per_frame = 2

    return frame_config


@pytest.fixture
def chain_config():
    chain_config = MagicMock
    chain_config.slots_per_epoch = 12

    return chain_config


@pytest.fixture
def blockstamp():
    blockstamp = MagicMock
    blockstamp.ref_epoch = 99

    return blockstamp


@pytest.mark.unit
@pytest.mark.parametrize(
    "slashings_in_frame, last_finalized_withdrawal_request_slot, expected",
    [
        (True, 144, 90),
        (False, 144, 98),
    ],
)
def test_find_earliest_slashed_epoch_rounded_to_frame(
    validators,
    frame_config,
    chain_config,
    blockstamp,
    slashings_in_frame,
    last_finalized_withdrawal_request_slot,
    expected,
):
    SafeBorder._retrieve_constants = MagicMock()
    SafeBorder._get_negative_rebase_border_epoch = MagicMock()
    SafeBorder._get_associated_slashings_border_epoch = MagicMock()
    SafeBorder._get_last_finalized_withdrawal_request_slot = MagicMock(
        return_value=last_finalized_withdrawal_request_slot
    )
    SafeBorder._slashings_in_frame = MagicMock(return_value=slashings_in_frame)

    web3Mock = MagicMock()
    web3Mock.lido_contracts = MagicMock()

    sb = SafeBorder(w3=web3Mock, blockstamp=blockstamp, chain_config=chain_config, frame_config=frame_config)

    actual = sb._find_earliest_slashed_epoch_rounded_to_frame(validators)

    assert expected == actual
