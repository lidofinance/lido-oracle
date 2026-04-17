from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
import responses
from eth_utils import add_0x_prefix
from requests.exceptions import ConnectionError as RequestsConnectionError
from timeout_decorator import TimeoutError as DecoratorTimeoutError
from web3_multi_provider.multi_http_provider import NoActiveProviderError

import variables
from metrics.prometheus.basic import (
    ACCOUNT_BALANCE,
    CYCLE_COUNT,
    LAST_CYCLE_TIMESTAMP,
    TRANSACTIONS_COUNT,
    CycleResult,
    Status,
    init_basic_metrics,
)
from modules.common.types import ModuleExecuteDelay
from modules.oracles.common.exceptions import (
    IncompatibleOracleVersion,
    IsNotMemberException,
)
from modules.oracles.common.oracle_module import OracleModule
from providers.http_provider import NotOkResponse
from providers.keys.client import KeysOutdatedException
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.configs import BlockDetailsResponseFactory
from type_aliases import BlockStamp
from utils.slot import InconsistentData, NoSlotsAvailable, SlotNotFinalized


class SimpleOracle(OracleModule):
    call_count: int = 0
    COMPATIBLE_CONTRACT_VERSION = 1
    COMPATIBLE_CONSENSUS_VERSION = 1

    def __init__(self, w3):
        self.report_contract = MagicMock()
        super().__init__(w3)

    def execute_module(self, blockstamp):
        self.call_count += 1
        return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

    def build_report(self, blockstamp):
        return ()

    def is_contract_reportable(self, blockstamp):
        return True

    def is_main_data_submitted(self, blockstamp):
        return False

    def is_reporting_allowed(self, blockstamp):
        return True

    def refresh_contracts(self):
        pass

    def is_contracts_addresses_changed(self):
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
    oracle.is_contracts_addresses_changed = Mock()
    oracle._receive_last_finalized_slot = Mock(return_value=ReferenceBlockStampFactory.build(slot_number=1))
    responses.get('http://localhost:8000/pulse/', status=HTTPStatus.OK)

    oracle.cycle_handler()
    assert oracle.call_count == 1
    assert oracle.is_contracts_addresses_changed.call_count == 1

    oracle.cycle_handler()
    assert oracle.call_count == 1
    assert oracle.is_contracts_addresses_changed.call_count == 1

    oracle._receive_last_finalized_slot = Mock(return_value=ReferenceBlockStampFactory.build(slot_number=2))
    oracle.cycle_handler()
    assert oracle.call_count == 2
    assert oracle.is_contracts_addresses_changed.call_count == 2


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
def test_cycle_no_fail_on_retryable_error(oracle: OracleModule, ex: Exception):
    oracle.w3.lido_contracts = MagicMock()
    with (
        patch.object(oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1111111)),
        patch.object(oracle.w3.lido_contracts, "has_contract_address_changed", return_value=False),
        patch.object(oracle, "execute_module", side_effect=ex),
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
def test_run_cycle_fails_on_critical_exceptions(oracle: OracleModule, ex: Exception):
    oracle.w3.lido_contracts = MagicMock()
    with (
        patch.object(oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1111111)),
        patch.object(oracle.w3.lido_contracts, "has_contract_address_changed", return_value=False),
        patch.object(oracle, "execute_module", side_effect=ex),
        pytest.raises(type(ex), match="Fake exception"),
    ):
        oracle._cycle()
    # test node availability
    with (
        patch.object(oracle, "_receive_last_finalized_slot", side_effect=ex),
        pytest.raises(type(ex), match="Fake exception"),
    ):
        oracle._cycle()


@pytest.mark.unit
def test_init_basic_metrics__all_labels__metrics_exist(web3):
    with patch.object(variables, 'ACCOUNT', Mock(address='0x0000000000000000000000000000000000000001')):
        init_basic_metrics(web3)

        for status in Status:
            assert TRANSACTIONS_COUNT.labels(status=status.value) is not None
        for result in CycleResult:
            assert CYCLE_COUNT.labels(result=result.value) is not None
        assert LAST_CYCLE_TIMESTAMP.labels(result=CycleResult.SUCCESS.value)._value.get() > 0
        assert ACCOUNT_BALANCE.labels(address='0x0000000000000000000000000000000000000001')._value.get() >= 0
        web3.telemetry_data_bus.update_account_balance_metric.assert_called_once()


@pytest.mark.unit
def test_cycle__successful_execution__records_success_metric(oracle: OracleModule):
    before = CYCLE_COUNT.labels(result=CycleResult.SUCCESS.value)._value.get()

    with (
        patch("modules.common.daemon_module.pulse"),
        patch.object(oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1111111)),
        patch.object(oracle, "execute_module", return_value=ModuleExecuteDelay.NEXT_FINALIZED_EPOCH),
    ):
        oracle._cycle()

    assert CYCLE_COUNT.labels(result=CycleResult.SUCCESS.value)._value.get() == before + 1
    assert LAST_CYCLE_TIMESTAMP.labels(result=CycleResult.SUCCESS.value)._value.get() > 0


@pytest.mark.unit
def test_cycle__retryable_error__records_error_metric(oracle: OracleModule):
    before = CYCLE_COUNT.labels(result=CycleResult.ERROR.value)._value.get()

    with (
        patch.object(oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1111111)),
        patch.object(oracle, "execute_module", side_effect=RequestsConnectionError("Fake")),
    ):
        oracle._cycle()

    assert CYCLE_COUNT.labels(result=CycleResult.ERROR.value)._value.get() == before + 1
    assert LAST_CYCLE_TIMESTAMP.labels(result=CycleResult.ERROR.value)._value.get() > 0


@pytest.mark.unit
def test_cycle__slot_below_threshold__records_success_metric(oracle: OracleModule):
    oracle._slot_threshold = 999999
    success_before = CYCLE_COUNT.labels(result=CycleResult.SUCCESS.value)._value.get()
    error_before = CYCLE_COUNT.labels(result=CycleResult.ERROR.value)._value.get()

    with patch.object(oracle, "_receive_last_finalized_slot", return_value=MagicMock(slot_number=1)):
        oracle._cycle()

    assert CYCLE_COUNT.labels(result=CycleResult.SUCCESS.value)._value.get() == success_before + 1
    assert CYCLE_COUNT.labels(result=CycleResult.ERROR.value)._value.get() == error_before
