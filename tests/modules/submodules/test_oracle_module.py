import pytest

from src.modules.submodules import oracle_module
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp


class SimpleOracle(BaseModule):
    call_count: int = 0

    def execute_module(self, blockstamp):
        self.call_count += 1


@pytest.fixture(autouse=True)
def set_default_sleep(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(oracle_module, "DEFAULT_SLEEP", 1)
        yield


@pytest.fixture()
def oracle(web3, consensus_client):
    return SimpleOracle(web3)


@pytest.mark.unit
def test_receive_last_finalized_slot(oracle):
    slot = oracle._receive_last_finalized_slot()
    assert slot == BlockStamp(
        block_root='0x01412064d5838f7b5111bf265dbbb6380da550149da5a1ec62a6c25b71b3bd87',
        state_root='0x96a3a4d229af1d3b809cb96a40c536e7287bf7ef07ae90c39be0f22475ac20dc',
        slot_number=50208,
        block_hash='0xac3e326576b16db5864545d3c8a4bfc6c91adbd0ac2f3f2946e7a949768c088d',
        block_number=49107,
    )


@pytest.mark.unit
def test_cycle_handler_run_once_per_slot(monkeypatch, oracle):
    slot = lambda slot: lambda *args, **kwargs: BlockStamp(
        block_root=None,
        state_root=None,
        slot_number=slot,
        block_hash='',
        block_number=None
    )
    monkeypatch.setattr(SimpleOracle, '_receive_last_finalized_slot', slot(1))
    oracle._cycle_handler()
    assert oracle.call_count == 1
    oracle._cycle_handler()
    assert oracle.call_count == 1
    monkeypatch.setattr(SimpleOracle, '_receive_last_finalized_slot', slot(2))
    oracle._cycle_handler()
    assert oracle.call_count == 2
