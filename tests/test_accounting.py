import pytest
from hexbytes import HexBytes

from src.modules.accounting import Accounting
from src.typings import SlotNumber


pytestmark = pytest.mark.skip(reason="Work in progress")


@pytest.fixture()
def past_slot_and_block(provider):
    return SlotNumber(4595230), '0xc001b15307c51190fb653a885bc9c5003a7b9dacceb75825fa376fc68e1c1a62'


@pytest.fixture()
def accounting(web3, consensus_client, provider) -> Accounting:
    return Accounting(web3, consensus_client)


@pytest.mark.unit
def test_slot_and_block_hash_for_report(accounting, past_slot_and_block):
    slot, block_hash = past_slot_and_block
    report_slot, report_block_hash = accounting._get_slot_and_block_hash_for_report(slot, block_hash)
    assert report_slot == 4595200
    assert report_block_hash == '0x6ff4626a6e2ac8f9f04804e6474ade244bcb68c563fcf07d86083250029be33e'


@pytest.mark.unit
def test_get_beacon_validators_stats_unit(accounting, past_slot_and_block, monkeypatch):
    validators = [{'validator': {'balance': 32}}, {'validator': {'balance': 32}}]
    monkeypatch.setattr(src.modules.accounting.accounting, 'get_lido_validators', lambda *args, **kwargs: validators)
    slot, block_hash = past_slot_and_block
    beacon_validators_count, beacon_validators_balance = accounting._get_beacon_validators_stats(slot, block_hash)
    assert beacon_validators_count == 2
    assert beacon_validators_balance == 64


@pytest.mark.unit
def test_get_exited_validators(accounting, past_slot_and_block, monkeypatch):
    # TODO epoch counting from 0, looks like a bug in the _get_exited_validators
    validator = lambda epoch: {'validator': {'validator': {'exit_epoch': epoch}}}
    validators = [validator(0), validator(1), validator(2)]
    monkeypatch.setattr(src.modules.accounting.accounting, 'get_lido_validators', lambda *args, **kwargs: validators)

    third_epoch = SlotNumber(64)
    validators = accounting._get_exited_validators(third_epoch, HexBytes("0x1"))
    assert len(validators) == 2

    second_epoch = SlotNumber(32)
    validators = accounting._get_exited_validators(second_epoch, HexBytes("0x1"))
    assert len(validators) == 1

