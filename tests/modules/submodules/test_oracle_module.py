from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
import responses
from eth_utils import add_0x_prefix
from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import TimeoutError as DecoratorTimeoutError
from web3_multi_provider.multi_http_provider import NoActiveProviderError

from src import variables
from src.modules.submodules.exceptions import (
    IncompatibleOracleVersion,
    IsNotMemberException,
)
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.providers.http_provider import NotOkResponse
from src.providers.keys.client import KeysOutdatedException
from src.types import BlockStamp
from src.utils.slot import InconsistentData, NoSlotsAvailable, SlotNotFinalized
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import BlockDetailsResponseFactory


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
def oracle(web3):
    return SimpleOracle(web3)


@pytest.mark.unit
def test_receive_last_finalized_slot(oracle):
    block_details = BlockDetailsResponseFactory.build()
    execution_payload = block_details.message.body.execution_payload
    oracle.w3.cc.get_block_details.return_value = block_details

    slot = oracle._receive_last_finalized_slot()

    assert slot == BlockStamp(
        state_root=block_details.message.state_root,
        slot_number=block_details.message.slot,
        block_hash=add_0x_prefix(execution_payload.block_hash),
        block_number=execution_payload.block_number,
        block_timestamp=execution_payload.timestamp,
    )


@pytest.mark.unit
@responses.activate
def test_cycle_handler_run_once_per_slot(oracle, web3):
    web3.lido_contracts.has_contract_address_changed = Mock()
    oracle._receive_last_finalized_slot = Mock(return_value=ReferenceBlockStampFactory.build(slot_number=1))
    responses.get('http://localhost:8000/pulse/', status=HTTPStatus.OK)

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
        DecoratorTimeoutError("Fake exception"),
        NoActiveProviderError.from_exceptions(message="Fake exception", exceptions=[RuntimeError('provider 1 error')]),
        RequestsConnectionError("Fake exception"),
        NotOkResponse(status=500, text="Fake exception"),
        NoSlotsAvailable("Fake exception"),
        SlotNotFinalized("Fake exception"),
        InconsistentData("Fake exception"),
        KeysOutdatedException("Fake exception"),
    ],
    ids=lambda param: f"{type(param).__name__}",
)
def test_cycle_no_fail_on_retryable_error(oracle: BaseModule, ex: Exception):
    oracle.w3.lido_contracts = MagicMock()
    with patch.object(
        oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1111111)
    ), patch.object(oracle.w3.lido_contracts, "has_contract_address_changed", return_value=False), patch.object(
        oracle, "execute_module", side_effect=ex
    ):
        oracle._cycle()
    # test node availability
    with patch.object(oracle, "_receive_last_finalized_slot", side_effect=ex):
        oracle._cycle()


@pytest.mark.unit
@pytest.mark.parametrize(
    "ex",
    [
        IsNotMemberException("Fake exception"),
        IncompatibleOracleVersion("Fake exception"),
    ],
    ids=lambda param: f"{type(param).__name__}",
)
def test_run_cycle_fails_on_critical_exceptions(oracle: BaseModule, ex: Exception):
    oracle.w3.lido_contracts = MagicMock()
    with patch.object(
        oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1111111)
    ), patch.object(oracle.w3.lido_contracts, "has_contract_address_changed", return_value=False), patch.object(
        oracle, "execute_module", side_effect=ex
    ), pytest.raises(
        type(ex), match="Fake exception"
    ):
        oracle._cycle()
    # test node availability
    with patch.object(oracle, "_receive_last_finalized_slot", side_effect=ex), pytest.raises(
        type(ex), match="Fake exception"
    ):
        oracle._cycle()
