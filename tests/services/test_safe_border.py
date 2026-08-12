from unittest.mock import Mock

import pytest

from src.services.safe_border import SafeBorder
from src.types import EpochNumber, ReferenceBlockStamp
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import ChainConfigFactory, OracleReportLimitsFactory


@pytest.fixture
def blockstamp() -> ReferenceBlockStamp:
    return ReferenceBlockStampFactory.build(ref_epoch=EpochNumber(100))


def make_safe_border(web3, blockstamp: ReferenceBlockStamp, request_timestamp_margin: int) -> SafeBorder:
    web3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=OracleReportLimitsFactory.build(request_timestamp_margin=request_timestamp_margin)
    )
    return SafeBorder(web3, blockstamp, ChainConfigFactory.build(slots_per_epoch=32, seconds_per_slot=12))


@pytest.mark.unit
@pytest.mark.parametrize(
    ('request_timestamp_margin', 'expected_shift'),
    [
        (0, 0),
        (1, 1),
        (384, 1),
        (385, 2),
    ],
)
def test_init__request_timestamp_margin__rounds_default_shift_up_to_epochs(
    web3,
    blockstamp: ReferenceBlockStamp,
    request_timestamp_margin: int,
    expected_shift: int,
) -> None:
    safe_border = make_safe_border(web3, blockstamp, request_timestamp_margin)

    assert safe_border.finalization_default_shift == expected_shift


@pytest.mark.unit
def test_get_safe_border_epoch__turbo_mode__uses_default_shift(web3, blockstamp: ReferenceBlockStamp) -> None:
    safe_border = make_safe_border(web3, blockstamp, request_timestamp_margin=24 * 384)

    result = safe_border.get_safe_border_epoch(is_bunker=False)

    assert result == blockstamp.ref_epoch - 24
    web3.lido_contracts.oracle_daemon_config.bunker_finalization_delay_epochs.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    ('bunker_delay', 'expected_shift'),
    [
        (9_000, 9_000),
        (10, 24),
    ],
)
def test_get_safe_border_epoch__bunker_mode__uses_larger_shift(
    web3,
    blockstamp: ReferenceBlockStamp,
    bunker_delay: int,
    expected_shift: int,
) -> None:
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=EpochNumber(10_000))
    safe_border = make_safe_border(web3, blockstamp, request_timestamp_margin=24 * 384)
    web3.lido_contracts.oracle_daemon_config.bunker_finalization_delay_epochs = Mock(return_value=bunker_delay)

    result = safe_border.get_safe_border_epoch(is_bunker=True)

    assert result == blockstamp.ref_epoch - expected_shift
    web3.lido_contracts.oracle_daemon_config.bunker_finalization_delay_epochs.assert_called_once_with(
        blockstamp.block_hash
    )


@pytest.mark.unit
@pytest.mark.parametrize('is_bunker', [False, True])
def test_get_safe_border_epoch__shift_exceeds_reference_epoch__returns_genesis(web3, is_bunker: bool) -> None:
    blockstamp = ReferenceBlockStampFactory.build(ref_epoch=EpochNumber(10))
    safe_border = make_safe_border(web3, blockstamp, request_timestamp_margin=24 * 384)
    web3.lido_contracts.oracle_daemon_config.bunker_finalization_delay_epochs = Mock(return_value=9_000)

    result = safe_border.get_safe_border_epoch(is_bunker=is_bunker)

    assert result == 0
