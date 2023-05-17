from unittest.mock import MagicMock, patch

import pytest

from src.typings import ReferenceBlockStamp
from src.services.safe_border import SafeBorder
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory, OracleReportLimitsFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory

from src.constants import EPOCHS_PER_SLASHINGS_VECTOR, MIN_VALIDATOR_WITHDRAWABILITY_DELAY


@pytest.fixture()
def past_blockstamp():
    yield ReferenceBlockStampFactory.build()


@pytest.fixture
def finalization_max_negative_rebase_epoch_shift():
    return 128


@pytest.fixture()
def subject(
    past_blockstamp,
    web3,
    contracts,
    keys_api_client,
    consensus_client,
    lido_validators,
    finalization_max_negative_rebase_epoch_shift,
):
    with patch.object(
        SafeBorder,
        '_fetch_oracle_report_limits_list',
        return_value=OracleReportLimitsFactory.build(request_timestamp_margin=8 * 12 * 32),
    ), patch.object(
        SafeBorder,
        '_fetch_finalization_max_negative_rebase_epoch_shift',
        return_value=finalization_max_negative_rebase_epoch_shift,
    ):
        safe_border = SafeBorder(web3, past_blockstamp, ChainConfigFactory.build(), FrameConfigFactory.build())

    return safe_border


@pytest.mark.integration
def test_happy_path(subject, past_blockstamp: ReferenceBlockStamp):
    is_bunker_mode = False

    assert (
        subject.get_safe_border_epoch(is_bunker_mode) == past_blockstamp.ref_epoch - subject.finalization_default_shift
    )


@pytest.mark.integration
def test_bunker_mode_negative_rebase(subject, past_blockstamp: ReferenceBlockStamp):
    is_bunker_mode = True

    subject._get_bunker_start_or_last_successful_report_epoch = MagicMock(return_value=past_blockstamp.ref_epoch)
    subject._get_earliest_slashed_epoch_among_incomplete_slashings = MagicMock(return_value=None)

    assert (
        subject.get_safe_border_epoch(is_bunker_mode) == past_blockstamp.ref_epoch - subject.finalization_default_shift
    )


@pytest.mark.integration
def test_bunker_mode_associated_slashing_predicted(
    subject: SafeBorder, past_blockstamp: ReferenceBlockStamp, finalization_max_negative_rebase_epoch_shift: int
):
    is_bunker_mode = True
    withdrawable_epoch = past_blockstamp.ref_epoch + 128
    exit_epoch = past_blockstamp.ref_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY

    subject._get_bunker_start_or_last_successful_report_epoch = MagicMock(
        return_value=past_blockstamp.ref_epoch - finalization_max_negative_rebase_epoch_shift - 1
    )
    subject.w3.lido_validators.get_lido_validators = MagicMock(
        return_value=[
            LidoValidatorFactory.build(
                validator=ValidatorStateFactory.build(
                    slashed=True, withdrawable_epoch=withdrawable_epoch, exit_epoch=exit_epoch
                )
            )
        ]
    )

    assert subject.get_safe_border_epoch(is_bunker_mode) == (
        subject.round_epoch_by_frame(withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR)
        - subject.finalization_default_shift
    )


@pytest.mark.integration
def test_bunker_mode_associated_slashing_unpredicted(
    subject: SafeBorder, past_blockstamp: ReferenceBlockStamp, finalization_max_negative_rebase_epoch_shift: int
):
    is_bunker_mode = True
    withdrawable_epoch = past_blockstamp.ref_epoch + 128
    exit_epoch = withdrawable_epoch - MIN_VALIDATOR_WITHDRAWABILITY_DELAY
    activation_epoch = withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR - 2

    subject._get_blockstamp = MagicMock(return_value=past_blockstamp)
    subject._get_bunker_start_or_last_successful_report_epoch = MagicMock(
        return_value=past_blockstamp.ref_epoch - finalization_max_negative_rebase_epoch_shift - 1
    )
    subject._get_last_finalized_withdrawal_request_slot = MagicMock(
        return_value=withdrawable_epoch - EPOCHS_PER_SLASHINGS_VECTOR - 2
    )
    subject.w3.lido_validators.get_lido_validators = MagicMock(
        return_value=[
            LidoValidatorFactory.build(
                validator=ValidatorStateFactory.build(
                    slashed=True,
                    withdrawable_epoch=withdrawable_epoch,
                    exit_epoch=exit_epoch,
                    activation_epoch=activation_epoch,
                )
            )
        ]
    )

    assert subject.get_safe_border_epoch(is_bunker_mode) == (
        subject.round_epoch_by_frame(activation_epoch) - subject.finalization_default_shift
    )
