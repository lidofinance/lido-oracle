from unittest.mock import MagicMock, patch, Mock

import pytest
from eth_account import Account
from requests import Response

from src import variables
from src.web3py.extensions.tx_bundle import TransactionBundle


@pytest.mark.unit
@patch("src.web3py.extensions.tx_bundle.TransactionBundle._send_payload")
@patch("time.sleep", return_value=None)
def test_send_bundle(sleep, mock_send_payload):
    w3 = MagicMock()
    w3.eth.block_number = 100
    txs = ['tx1', 'tx2']

    TransactionBundle._send_bundle(w3, txs)

    mock_send_payload.assert_called_once_with(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_sendBundle",
            "params": [{'txs': txs}],
        },
        range(101, 107),
    )


@pytest.mark.unit
@patch("eth_account.Account.create", return_value=Account.from_key(b'0' * 32))
@patch("requests.post")
def test_send_payload(mock_post, account):
    variables.PRIVATE_RELAYS_LIST = ['relay1', 'relay2']

    blocks = ["0x65", "0x66", "0x67", "0x68", "0x69", "0x6a"]

    TransactionBundle._send_payload({'params': [{}]}, range(101, 107))

    assert mock_post.call_count == len(list(range(101, 107))) * len(variables.PRIVATE_RELAYS_LIST)

    for i in range(12):
        assert (
            '0x827b44d53Df2854057713b25Cdd653Eb70Fe36C4'
            in mock_post.call_args_list[i][1]['headers']['X-Flashbots-Signature']
        )
        assert blocks[i // len(variables.PRIVATE_RELAYS_LIST)] in mock_post.call_args_list[i][1]['data']

        if i % 2:
            assert mock_post.call_args_list[i][0][0] == "relay2"
        else:
            assert mock_post.call_args_list[i][0][0] == "relay1"


@pytest.mark.unit
@patch("requests.post", side_effect=[Exception('fail'), Response(), Exception('fail'), Response()])
def test_send_payload_error(mock_post, caplog):
    variables.PRIVATE_RELAYS_LIST = ['relay1', 'relay2']

    with caplog.at_level("INFO"):
        TransactionBundle._send_payload({'params': [{}]}, range(1, 3))
        assert 'Failed to send payload' in caplog.messages[0]
        assert 'Sent bundle to relay' in caplog.messages[1]
        assert 'Failed to send payload' in caplog.messages[2]
        assert 'Sent bundle to relay' in caplog.messages[3]


@pytest.mark.unit
def test_sign_transactions():
    w3 = MagicMock()
    w3.eth.get_transaction_count.return_value = 7
    w3.eth.get_block.return_value = {"baseFeePerGas": 39}
    w3.eth.fee_history.return_value = {'reward': [[100]]}

    variables.ACCOUNT = Account.from_key(b'0' * 32)

    tx_mock_1 = MagicMock()
    tx_mock_1.build_transaction.return_value = {
        "maxFeePerGas": 123,
        "maxPriorityFeePerGas": 45,
        "gas": 21000,
    }

    tx_mock_2 = MagicMock()
    tx_mock_2.build_transaction.return_value = {
        "maxFeePerGas": 123,
        "maxPriorityFeePerGas": 45,
        "gas": 21000,
    }

    signed_tx = MagicMock()
    signed_tx.rawTransaction.hex.return_value = '0x0'

    w3.eth.account.sign_transaction = Mock(side_effect=lambda x, y: signed_tx)

    result = TransactionBundle._sign_transactions(w3, [tx_mock_1, tx_mock_2])

    tx_mock_1.build_transaction.assert_called_once_with(
        {'maxFeePerGas': 50000078, 'maxPriorityFeePerGas': 50000000, 'gas': 7000000, 'nonce': 7}
    )
    tx_mock_2.build_transaction.assert_called_once_with(
        {'maxFeePerGas': 50000078, 'maxPriorityFeePerGas': 50000000, 'gas': 7000000, 'nonce': 8}
    )

    assert result == ['0x0', '0x0']
