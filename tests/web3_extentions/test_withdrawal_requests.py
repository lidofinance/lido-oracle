from unittest.mock import Mock

import pytest
from hexbytes import HexBytes

from src.providers.execution.exceptions import InconsistentData
from src.web3py.types import Web3
from tests.factory.blockstamp import ReferenceBlockStampFactory

blockstamp = ReferenceBlockStampFactory.build()


@pytest.mark.unit
@pytest.mark.usefixtures("withdrawal_requests")
def test_queue_len(web3: Web3):
    web3.eth.get_storage_at = Mock(
        side_effect=[
            HexBytes(bytes.fromhex("")),
            HexBytes(bytes.fromhex("")),
        ]
    )
    assert web3.withdrawal_requests.get_queue_len(blockstamp) == 0

    web3.eth.get_storage_at = Mock(
        side_effect=[
            HexBytes(bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000")),
            HexBytes(bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000")),
        ]
    )
    assert web3.withdrawal_requests.get_queue_len(blockstamp) == 0

    web3.eth.get_storage_at = Mock(
        side_effect=[
            HexBytes(bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000000")),
            HexBytes(bytes.fromhex("00000000000000000000000000000000000000000000000000000000000001c7")),
        ]
    )
    assert web3.withdrawal_requests.get_queue_len(blockstamp) == 455

    web3.eth.get_storage_at = Mock(
        side_effect=[
            HexBytes(bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000020")),
            HexBytes(bytes.fromhex("00000000000000000000000000000000000000000000000000000000000001c7")),
        ]
    )
    assert web3.withdrawal_requests.get_queue_len(blockstamp) == 423

    web3.eth.get_storage_at = Mock(
        side_effect=[
            HexBytes(bytes.fromhex("00000000000000000000000000000000000000000000000000000000000001c7")),
            HexBytes(bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000020")),
        ]
    )
    with pytest.raises(InconsistentData):
        web3.withdrawal_requests.get_queue_len(blockstamp)
