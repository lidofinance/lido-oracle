from typing import Type
from unittest.mock import Mock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import TimeoutError as DecoratorTimeoutError
from web3_multi_provider.multi_http_provider import NoActiveProviderError

from src import variables
from src.modules.submodules.exceptions import IncompatibleOracleVersion, IsNotMemberException
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.providers.http_provider import NotOkResponse
from src.providers.keys.client import KeysOutdatedException
from src.types import BlockStamp
from src.utils.slot import InconsistentData, NoSlotsAvailable, SlotNotFinalized
from tests.factory.blockstamp import ReferenceBlockStampFactory


class SimpleOracle(BaseModule):
    call_count: int = 0

    def execute_module(self, blockstamp):
        self.call_count += 1
        return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

    def refresh_contracts(self):
        pass


@pytest.fixture(autouse=True)
def set_default_sleep(monkeypatch):
    with monkeypatch.context():
        monkeypatch.setattr(variables, "CYCLE_SLEEP_IN_SECONDS", 1)
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
    oracle.cycle_handler()
    assert oracle.call_count == 1
    assert web3.lido_contracts.has_contract_address_changed.call_count == 1

    oracle.cycle_handler()
    assert oracle.call_count == 1
    assert web3.lido_contracts.has_contract_address_changed.call_count == 1

    oracle._receive_last_finalized_slot = Mock(return_value=ReferenceBlockStampFactory.build(slot_number=2))
    oracle.cycle_handler()
    assert oracle.call_count == 2
    assert web3.lido_contracts.has_contract_address_changed.call_count == 2


@pytest.mark.unit
def test_run_as_daemon(oracle):
    times = 0

    def _throw_on_third_call():
        nonlocal times
        times += 1
        if times == 3:
            raise Exception("Cycle failed")

    oracle.cycle_handler = Mock(side_effect=_throw_on_third_call)

    with pytest.raises(Exception, match="Cycle failed"):
        oracle.run_as_daemon()

    assert oracle.cycle_handler.call_count == 3


@pytest.mark.unit
@pytest.mark.parametrize(
    "ex",
    [
        DecoratorTimeoutError,
        NoActiveProviderError,
        RequestsConnectionError,
        NotOkResponse,
        NoSlotsAvailable,
        SlotNotFinalized,
        InconsistentData,
        KeysOutdatedException,
    ],
)
def test_run_cycle_no_fail_on_retryable_error(oracle: BaseModule, ex: Type[Exception]):
    def _throw_with(*args):
        if ex is NotOkResponse:
            raise ex(status=500, text="Fake exception")  # type: ignore
        raise ex("Fake exception")

    oracle.execute_module = Mock(side_effect=_throw_with)

    ret = oracle.run_cycle(ReferenceBlockStampFactory.build())
    assert ret is ModuleExecuteDelay.NEXT_SLOT


@pytest.mark.unit
@pytest.mark.parametrize(
    "ex",
    [
        IsNotMemberException,
        IncompatibleOracleVersion,
    ],
)
def test_run_cycle_fails_on_critical_exceptions(oracle: BaseModule, ex: Type[Exception]):
    def _throw_with(*args):
        raise ex("Fake exception")

    oracle.execute_module = Mock(side_effect=_throw_with)

    with pytest.raises(ex, match="Fake exception"):
        oracle.run_cycle(ReferenceBlockStampFactory.build())
