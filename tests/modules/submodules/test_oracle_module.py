from unittest.mock import Mock

import pytest

from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.typings import BlockStamp
from src.web3py.extensions import LidoContracts
from tests.factory.blockstamp import ReferenceBlockStampFactory


class SimpleOracle(BaseModule):
    call_count: int = 0

    def execute_module(self, blockstamp):
        self.call_count += 1
        return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

    def contracts_refresh(self):
        pass

    def clear_cache(self):
        pass


@pytest.fixture(autouse=True)
def set_default_sleep(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(BaseModule, "DEFAULT_SLEEP", 1)
        yield


@pytest.fixture()
def oracle(web3, consensus_client):
    return SimpleOracle(web3)


@pytest.mark.unit
def test_receive_last_finalized_slot(oracle):
    slot = oracle._receive_last_finalized_slot()
    assert slot == BlockStamp(
        state_root='0x96a3a4d229af1d3b809cb96a40c536e7287bf7ef07ae90c39be0f22475ac20dc',
        slot_number=50208,
        block_hash='0xac3e326576b16db5864545d3c8a4bfc6c91adbd0ac2f3f2946e7a949768c088d',
        block_number=49107,
        block_timestamp=1675866096,
    )


@pytest.mark.unit
def test_cycle_handler_run_once_per_slot(oracle, contracts, web3):
    web3.lido_contracts.has_contract_address_changed = Mock()
    oracle._receive_last_finalized_slot = Mock(return_value=ReferenceBlockStampFactory.build(slot_number=1))
    oracle._cycle_handler()
    assert oracle.call_count == 1
    assert web3.lido_contracts.has_contract_address_changed.call_count == 1

    oracle._cycle_handler()
    assert oracle.call_count == 1
    assert web3.lido_contracts.has_contract_address_changed.call_count == 1

    oracle._receive_last_finalized_slot = Mock(return_value=ReferenceBlockStampFactory.build(slot_number=2))
    oracle._cycle_handler()
    assert oracle.call_count == 2
    assert web3.lido_contracts.has_contract_address_changed.call_count == 2
