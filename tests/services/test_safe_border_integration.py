import pytest
from unittest.mock import MagicMock

from src.services.safe_border import SafeBorder

@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    return SafeBorder(web3)

def test_no_bunker_mode(subject, past_blockstamp):
    assert subject.get_safe_border_epoch(past_blockstamp) == int(past_blockstamp.slot_number / 32) - 8

def test_bunker_mode_associated_slashing(subject, past_blockstamp):
    subject.get_bunker_mode = MagicMock(return_value=True)
    # ref_epoch = int(blockstamp.slot_number / 32)
    subject.get_safe_border_epoch(past_blockstamp)

def test_bunker_mode_negative_rebase(subject, past_blockstamp):
    pass