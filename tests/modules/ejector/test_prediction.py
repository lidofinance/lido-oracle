from hexbytes import HexBytes

from src.modules.ejector.prediction import RewardsPredictionService


def test_group_by_tx_hash():
    events_1 = [
        {'transactionHash': HexBytes('0x123'), 'args': {'name': 'first'}},
        {'transactionHash': HexBytes('0x456'), 'args': {'name': 'second'}},
    ]

    events_2 = [
        {'transactionHash': HexBytes('0x456'), 'args': {'value': 2}},
        {'transactionHash': HexBytes('0x123'), 'args': {'value': 1}},
    ]

    result = RewardsPredictionService._group_events_by_transaction_hash(events_1, events_2)

    assert len(result) == 2

    for event_data in result:
        if event_data['name'] == 'first':
            assert event_data['value'] == 1
        elif event_data['name'] == 'second':
            assert event_data['value'] == 2
        else:
            # No other events should be here
            assert False
