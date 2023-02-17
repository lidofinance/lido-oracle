import pytest
from unittest.mock import MagicMock

from src.typings import BlockStamp
from src.services.safe_border import SafeBorder

@pytest.fixture()
def blockstamp():
    return BlockStamp(
        block_root='0xf03b8bd6379c89654ad313d98284eda8d9cf2ab78dfb509e3b5d0dbe30f6d95c', 
        state_root='0x7818f12273c299881370ade970fd380f232e214e1ad59288feed34cc4322f551', 
        slot_number=106624, block_hash='0xd9dd59d7e631c998a5d89aba0358d17f8d89f545d3307627fc77fe63eb98d7d9',
        block_number=101593
    )

@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return SafeBorder(web3)

def test_no_bunker_mode(subject, blockstamp):
    assert subject.get_safe_border_epoch(blockstamp) == int(blockstamp.slot_number / 32) - 8

def test_bunker_mode_associated_slashing(subject, blockstamp):
    subject.get_bunker_mode = MagicMock(return_value=True)
    # ref_epoch = int(blockstamp.slot_number / 32)
    subject.get_safe_border_epoch(blockstamp)

def test_bunker_mode_negative_rebase(subject, blockstamp):
    pass