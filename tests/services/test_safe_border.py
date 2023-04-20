import pytest
from unittest.mock import MagicMock, patch
from hexbytes import HexBytes
from tests.factory.blockstamp import ReferenceBlockStampFactory
from src.services.validator_state import LidoValidatorStateService
from src.modules.submodules.typings import ChainConfig, FrameConfig
from src.services.safe_border import SafeBorder
from tests.factory.no_registry import ValidatorFactory
from src.utils import events
from src.typings import FrameNumber


@pytest.fixture
def blockstamp():
    TESTING_REF_EPOCH = 100

    return ReferenceBlockStampFactory.build(
        ref_slot=9024,
        ref_epoch=TESTING_REF_EPOCH)


@pytest.mark.unit
def test_get_last_requested_to_exit_pubkeys(monkeypatch):
    def mock_get_events_in_past(*args, **kwargs):
        return [
            {
                'args': {'validatorPubkey': HexBytes('0x123')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x111')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x222')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x333')},
            },
            {
                'args': {'validatorPubkey': HexBytes('0x444')},
            }
        ]

    web3 = MagicMock()
    web3.lido_contracts.validators_exit_bus_oracle = MagicMock()
    monkeypatch.setattr(events, 'get_events_in_past', mock_get_events_in_past)

    lvss = LidoValidatorStateService(web3)
    extra_data_service = MagicMock()
    lvss.extra_data_service = extra_data_service
    lvss.get_validator_delinquent_timeout_in_slot = MagicMock()

    expected = {'0x0x0222', '0x0x0111', '0x0x0444', '0x0x0123', '0x0x0333'}
    actual = lvss.get_last_requested_to_exit_pubkeys(MagicMock(), MagicMock())

    assert actual == expected


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
    frame_config = MagicMock()
    frame_config.initial_epoch = 50
    frame_config.epochs_per_frame = 2

    return frame_config


@pytest.fixture
def chain_config():
    chain_config = MagicMock()
    chain_config.slots_per_epoch = 12

    return chain_config


@pytest.mark.unit
@pytest.mark.parametrize(
    "slashings_in_frame, last_finalized_withdrawal_request_slot, expected",
    [
        (True, 144, 90),
        (False, 144, 100),
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
    web3Mock = MagicMock()
    web3Mock.lido_contracts = MagicMock()

    with patch.object(
            SafeBorder,
            '_retrieve_constants',
            return_value=MagicMock,
    ), patch.object(
        SafeBorder,
        '_get_negative_rebase_border_epoch',
        return_value=MagicMock(),
    ), patch.object(
        SafeBorder,
        '_get_associated_slashings_border_epoch',
        return_value=MagicMock(),
    ), patch.object(
        SafeBorder,
        '_get_last_finalized_withdrawal_request_slot',
        return_value=last_finalized_withdrawal_request_slot
    ), patch.object(
        SafeBorder,
        '_slashings_in_frame',
        return_value=slashings_in_frame
    ):
        sb = SafeBorder(w3=web3Mock, blockstamp=blockstamp, chain_config=chain_config, frame_config=frame_config)
        actual = sb._find_earliest_slashed_epoch_rounded_to_frame(validators)

        assert expected == actual


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
    web3Mock = MagicMock()
    web3Mock.lido_contracts = MagicMock()

    with patch.object(
            SafeBorder,
            '_retrieve_constants',
            return_value=MagicMock(),
    ), patch.object(
        SafeBorder,
        '_get_negative_rebase_border_epoch',
        return_value=negative_rebase_border_epoch
    ), patch.object(
        SafeBorder,
        '_get_associated_slashings_border_epoch',
        return_value=associated_slashings_border_epoch
    ), patch.object(
        SafeBorder,
        '_get_default_requests_border_epoch',
        return_value=default_requests_border_epoch
    ):
        sb = SafeBorder(w3=web3Mock, blockstamp=MagicMock(), chain_config=MagicMock(), frame_config=MagicMock())
        actual = sb.get_safe_border_epoch(is_bunker=is_bunker)

        assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "get_bunker_timestamp, slots_per_epoch, last_processing_ref_slot, initial_epoch, expected",
    [
        (None, 12, 12, 1251, 0),
        (None, 12, 0, 1251, 1251),
    ],
)
def test_get_bunker_start_or_last_successful_report_epoch(
        get_bunker_timestamp, slots_per_epoch, last_processing_ref_slot, initial_epoch, expected
):
    web3Mock = MagicMock()
    web3Mock.lido_contracts.get_accounting_last_processing_ref_slot = MagicMock(return_value=last_processing_ref_slot)

    chain_config = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=slots_per_epoch,
        genesis_time=0,
    )

    frame_config = FrameConfig(
        initial_epoch=initial_epoch,
        epochs_per_frame=0,
        fast_lane_length_slots=0
    )

    with patch.object(
            SafeBorder,
            '_retrieve_constants',
            return_value=MagicMock(),
    ), patch.object(
        SafeBorder,
        '_get_negative_rebase_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_associated_slashings_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_default_requests_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_bunker_mode_start_timestamp',
        return_value=get_bunker_timestamp
    ):
        sb = SafeBorder(w3=web3Mock, blockstamp=MagicMock(), chain_config=chain_config, frame_config=frame_config)
        actual = sb._get_bunker_start_or_last_successful_report_epoch()

    assert expected == actual


@pytest.mark.unit
@pytest.mark.parametrize(
    "frame_number, slots_per_epoch, slashed_pubkeys, initial_epoch, expected",
    [
        (1, 12, {"pubkey_validator_1"}, 1251, 1),
    ],
)
def test_slashings_in_frame(validators, frame_number, slots_per_epoch, slashed_pubkeys, initial_epoch, expected):
    web3Mock = MagicMock()
    web3Mock.lido_validators.get_lido_validators = MagicMock(return_value=validators)

    chain_config = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=slots_per_epoch,
        genesis_time=0,
    )

    frame_config = FrameConfig(
        initial_epoch=initial_epoch,
        epochs_per_frame=225,
        fast_lane_length_slots=0
    )

    with patch.object(
            SafeBorder,
            '_retrieve_constants',
            return_value=MagicMock(),
    ), patch.object(
        SafeBorder,
        '_get_negative_rebase_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_associated_slashings_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_blockstamp',
        return_value=ReferenceBlockStampFactory.build(ref_epoch=4445)
    ):
        sb = SafeBorder(w3=web3Mock, blockstamp=MagicMock(), chain_config=chain_config, frame_config=frame_config)
        actual = sb._slashings_in_frame(FrameNumber(frame_number), slashed_pubkeys)

    assert expected == actual


@pytest.mark.unit
@pytest.mark.parametrize(
    "block_timestamp, bunker_start_timestamp, expected",
    [
        (1681911776, 1681911776 - 100, 1681911676),
        (1681911776, 1681911776 + 100, None),
    ],
)
def test_get_bunker_mode_start_timestamp(block_timestamp, bunker_start_timestamp, expected):
    web3Mock = MagicMock()
    web3Mock.lido_validators.get_lido_validators = MagicMock(return_value=validators)

    blockstamp = ReferenceBlockStampFactory.build(block_timestamp=block_timestamp)

    with patch.object(
            SafeBorder,
            '_retrieve_constants',
            return_value=MagicMock(),
    ), patch.object(
        SafeBorder,
        '_get_negative_rebase_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_associated_slashings_border_epoch',
        return_value=MagicMock()
    ), patch.object(
        SafeBorder,
        '_get_bunker_start_timestamp',
        return_value=bunker_start_timestamp
    ):
        sb = SafeBorder(w3=web3Mock, blockstamp=blockstamp, chain_config=MagicMock(), frame_config=MagicMock())
        actual = sb._get_bunker_mode_start_timestamp()

    assert expected == actual
