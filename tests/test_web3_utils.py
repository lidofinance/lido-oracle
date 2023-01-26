import pytest

from src.web3_utils.contract_frame_utils import get_latest_reportable_epoch


@pytest.mark.unit
def test_get_latest_reportable_epoch(web3, contracts, past_slot_and_block):
    slot, block_hash = past_slot_and_block
    reportable_epoch = get_latest_reportable_epoch(contracts.oracle, slot, block_hash)
    assert reportable_epoch == 143600
