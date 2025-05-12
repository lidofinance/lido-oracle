from unittest.mock import MagicMock, Mock

import pytest
from hexbytes import HexBytes
from web3.types import Wei

import src.services.prediction as prediction_module
from src.modules.submodules.types import ChainConfig
from src.services.prediction import RewardsPredictionService
from src.types import BlockNumber, SlotNumber
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def tr_hashes():
    return [
        '7f8fcaef4faa91a78c14c3eac86542',
        '07839b77ec9b93c95747b8de05ba03',
        '9f8018bbabd97cd3f0d27007a8d11a',
        '3472fd40eb87b8dd1069da56daaa17',
        '7c3a071c009b8eb39d07fb27c51fa1',
        '2335edcb12bf3e7a530f81d1bb46d7',
        '6b02f3dcfc5ea65e7ade78c38d3a59',
        '2d558d71920bc6b8344acfcdd5b587',
        '2f7d722b4584d3a053258f5c985fd2',
        '749390e4da86fae90b2bea60af3459',
        '184d9f0810ea02e20eef711f39a6eb',
        '3f319d0cef2d4150ff3c63d87262a6',
        '4e23a53dc4e940317f3f54be2a5662',
    ]


@pytest.fixture()
def eth_distributed_logs(tr_hashes):
    return [
        {
            'transactionHash': tr_hashes[0],
            'args': {
                'reportTimestamp': 1675441364,
                'withdrawalsWithdrawn': Wei(500000000000000000),
                'executionLayerRewardsWithdrawn': Wei(500000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[1],
            'args': {
                'reportTimestamp': 1675441376,
                'withdrawalsWithdrawn': Wei(5000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(400000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[2],
            'args': {
                'reportTimestamp': 1675441388,
                'withdrawalsWithdrawn': Wei(7000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(700000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[3],
            'args': {
                'reportTimestamp': 1675441400,
                'withdrawalsWithdrawn': Wei(9000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(900000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[4],
            'args': {
                'reportTimestamp': 1675441424,
                'withdrawalsWithdrawn': Wei(1000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(100000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[5],
            'args': {
                'reportTimestamp': 1675441436,
                'withdrawalsWithdrawn': Wei(11000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(1100000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[6],
            'args': {
                'reportTimestamp': 1675441448,
                'withdrawalsWithdrawn': Wei(14000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(1400000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[7],
            'args': {
                'reportTimestamp': 1675441460,
                'withdrawalsWithdrawn': Wei(15000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(1500000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[8],
            'args': {
                'reportTimestamp': 1675441472,
                'withdrawalsWithdrawn': Wei(17000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(1700000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[9],
            'args': {
                'reportTimestamp': 1675441484,
                'withdrawalsWithdrawn': Wei(21000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(21000000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[10],
            'args': {
                'reportTimestamp': 1675441496,
                'withdrawalsWithdrawn': Wei(32000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(32000000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[11],
            'args': {
                'reportTimestamp': 1675441508,
                'withdrawalsWithdrawn': Wei(64000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(64000000000000000000),
            },
        },
        {
            'transactionHash': tr_hashes[12],
            'args': {
                'reportTimestamp': 1675441520,
                'withdrawalsWithdrawn': Wei(132000000000000000000),
                'executionLayerRewardsWithdrawn': Wei(132000000000000000000),
            },
        },
    ]


@pytest.fixture()
def token_rebased_logs(tr_hashes):
    return [
        {
            'transactionHash': tr_hashes[0],
            'args': {
                'reportTimestamp': 1675441364,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[1],
            'args': {
                'reportTimestamp': 1675441376,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[2],
            'args': {
                'reportTimestamp': 1675441388,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[3],
            'args': {
                'reportTimestamp': 1675441400,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[4],
            'args': {
                'reportTimestamp': 1675441424,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[5],
            'args': {
                'reportTimestamp': 1675441436,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[6],
            'args': {
                'reportTimestamp': 1675441448,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[7],
            'args': {
                'reportTimestamp': 1675441460,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[8],
            'args': {
                'reportTimestamp': 1675441472,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[9],
            'args': {
                'reportTimestamp': 1675441484,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[10],
            'args': {
                'reportTimestamp': 1675441496,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[11],
            'args': {
                'reportTimestamp': 1675441508,
                'timeElapsed': 12,
            },
        },
        {
            'transactionHash': tr_hashes[12],
            'args': {
                'reportTimestamp': 1675441520,
                'timeElapsed': 12,
            },
        },
    ]


@pytest.mark.unit
def test_get_rewards_no_matching_events(web3):
    bp = ReferenceBlockStampFactory.build(
        block_number=BlockNumber(14),
        block_timestamp=1675441520,
        ref_slot=SlotNumber(100000),
        slot_number=SlotNumber(100000),
        block_hash=None,
    )
    cc = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )
    web3.lido_contracts.lido.events = MagicMock()
    web3.lido_contracts.lido.events.ETHDistributed.get_logs.return_value = []
    web3.lido_contracts.lido.events.TokenRebased.get_logs.return_value = []
    web3.lido_contracts.oracle_daemon_config.prediction_duration_in_slots.return_value = 12

    p = RewardsPredictionService(web3)

    rewards = p.get_rewards_per_epoch(bp, cc)

    assert rewards == Wei(0)


@pytest.mark.unit
def test_get_rewards_prediction(web3, monkeypatch: pytest.MonkeyPatch):
    bp = ReferenceBlockStampFactory.build(
        block_number=BlockNumber(14),
        block_timestamp=1675441520,
        ref_slot=SlotNumber(100000),
        slot_number=14,
        block_hash=None,
    )

    cc = ChainConfig(
        slots_per_epoch=32,
        seconds_per_slot=12,
        genesis_time=0,
    )

    web3.lido_contracts.oracle_daemon_config.prediction_duration_in_slots = Mock(return_value=12)

    SOME_EVENTS = object()

    with monkeypatch.context() as m:
        m.setattr(
            prediction_module,
            "get_events_in_past",
            MagicMock(return_value=SOME_EVENTS),
        )

        m.setattr(
            RewardsPredictionService,
            "_group_events_by_transaction_hash",
            MagicMock(
                return_value=[
                    {
                        "postCLBalance": Wei(24),
                        "withdrawalsWithdrawn": Wei(0),
                        "preCLBalance": Wei(0),
                        "executionLayerRewardsWithdrawn": Wei(0),
                        "timeElapsed": 12,
                    },
                    {
                        "postCLBalance": Wei(0),
                        "withdrawalsWithdrawn": Wei(0),
                        "preCLBalance": Wei(0),
                        "executionLayerRewardsWithdrawn": Wei(12),
                        "timeElapsed": 12,
                    },
                ]
            ),
        )

        p = RewardsPredictionService(web3)
        rewards = p.get_rewards_per_epoch(bp, cc)
        assert rewards == Wei(576)


@pytest.mark.unit
@pytest.mark.parametrize(
    "events_1, events_2",
    [
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
            ],
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 3}},
            ],
        ),
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
            ],
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
                {"transactionHash": HexBytes("0x567"), "args": {"value": 3}},
            ],
        ),
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
                {"transactionHash": HexBytes("0x567"), "args": {"value": 3}},
            ],
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
            ],
        ),
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 3}},
            ],
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
            ],
        ),
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x123"), "args": {"value": 1}},
            ],
            [
                {"transactionHash": HexBytes("0x345"), "args": {"value": 2}},
                {"transactionHash": HexBytes("0x567"), "args": {"value": 1}},
            ],
        ),
    ],
)
def test_group_events_inconsistent(events_1, events_2):
    with pytest.raises(prediction_module.InconsistentEvents, match="Events are inconsistent"):
        RewardsPredictionService._group_events_by_transaction_hash(events_1, events_2)


@pytest.mark.unit
@pytest.mark.parametrize(
    "events_1, events_2, expected",
    [
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"a": 1}},
                {"transactionHash": HexBytes("0x123"), "args": {"a": 2}},
            ],
            [
                {"transactionHash": HexBytes("0x123"), "args": {"a": 3}},
                {"transactionHash": HexBytes("0x456"), "args": {"a": 4}},
            ],
            [
                {"a": 3},
                {"a": 4},
            ],
        ),
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"a": 1}},
                {"transactionHash": HexBytes("0x123"), "args": {"a": 2}},
            ],
            [
                {"transactionHash": HexBytes("0x123"), "args": {"b": 3}},
                {"transactionHash": HexBytes("0x456"), "args": {"b": 4}},
            ],
            [
                {"a": 2, "b": 3},
                {"a": 1, "b": 4},
            ],
        ),
        (
            [
                {"transactionHash": HexBytes("0x456"), "args": {"a": 1}},
                {"transactionHash": HexBytes("0x123"), "args": {"a": 2}},
            ],
            [
                {"transactionHash": HexBytes("0x123"), "args": {}},
                {"transactionHash": HexBytes("0x456"), "args": {"b": 4}},
            ],
            [
                {"a": 2},
                {"a": 1, "b": 4},
            ],
        ),
    ],
)
def test_group_events(events_1, events_2, expected):
    actual = RewardsPredictionService._group_events_by_transaction_hash(events_1, events_2)
    assert actual == expected, "Unexpected merged events array"
