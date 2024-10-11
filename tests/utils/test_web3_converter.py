import pytest

from src.modules.submodules.types import ChainConfig, FrameConfig
from src.types import EpochNumber, FrameNumber, SlotNumber
from src.utils.web3converter import Web3Converter
from tests.factory.configs import ChainConfigFactory, FrameConfigFactory


@pytest.fixture
def frame_config() -> FrameConfig:
    return FrameConfigFactory.build(
        epochs_per_frame=2,
    )


@pytest.fixture
def chain_config() -> ChainConfig:
    return ChainConfigFactory.build(
        slots_per_epoch=12,
        seconds_per_slot=3,
        genesis_time=0,
    )


@pytest.fixture
def converter(frame_config: FrameConfig, chain_config: ChainConfig) -> Web3Converter:
    return Web3Converter(chain_config, frame_config)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (1, 12),
        (2, 24),
    ],
)
def test_get_epoch_first_slot(converter: Web3Converter, value: int, expected: int):
    # NOTE: may be add checks for negative values inside the constructor of EpochNumber
    assert converter.get_epoch_first_slot(EpochNumber(value)) is SlotNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 23),
        (1, 47),
        (2, 71),
    ],
)
def test_get_frame_last_slot(converter: Web3Converter, value: int, expected: int):
    # NOTE: may be add checks for negative values inside the constructor of FrameNumber
    assert converter.get_frame_last_slot(FrameNumber(value)) is SlotNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (1, 24),
        (2, 48),
    ],
)
def test_get_frame_first_slot(converter: Web3Converter, value: int, expected: int):
    assert converter.get_frame_first_slot(FrameNumber(value)) is SlotNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (1, 0),
        (42, 3),
    ],
)
def test_get_epoch_by_slot(converter: Web3Converter, value: int, expected: int):
    assert converter.get_epoch_by_slot(SlotNumber(value)) is EpochNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (12, 0),
        (77, 2),
    ],
)
def test_get_epoch_by_timestamp(converter: Web3Converter, value: int, expected: int):
    assert converter.get_epoch_by_timestamp(value) is EpochNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (2, 0),
        (3, 1),
        (12, 4),
    ],
)
def test_get_slot_by_timestamp(converter: Web3Converter, value: int, expected: int):
    assert converter.get_slot_by_timestamp(value) is SlotNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (2, 0),
        (144, 6),
    ],
)
def test_get_frame_by_slot(converter: Web3Converter, value: int, expected: int):
    assert converter.get_frame_by_slot(SlotNumber(value)) is FrameNumber(expected)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0),
        (2, 1),
        (17, 8),
    ],
)
def test_get_frame_by_epoch(converter: Web3Converter, value: int, expected: int):
    assert converter.get_frame_by_epoch(EpochNumber(value)) is FrameNumber(expected)
