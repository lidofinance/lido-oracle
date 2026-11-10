from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from src.providers.execution.contracts.lido_locator import LidoLocatorContract
from src.providers.execution.contracts.oracle_daemon_config import OracleDaemonConfigContract
from src.providers.execution.contracts.staking_router import StakingRouterContract
from src.providers.execution.contracts.triggerable_withdrawals_bus import (
    TriggerableWithdrawalsBusContract,
    WithdrawalIntent,
)
from src.types import Gwei


def _intent(pubkey_byte: int, amount: int) -> SimpleNamespace:
    return SimpleNamespace(pubkey=bytes([pubkey_byte]) * 48, amount=amount)


@pytest.mark.unit
class TestGetUnprocessedIntents:
    def test_get_unprocessed_intents__more_than_one_page__all_pages_in_order(self, monkeypatch):
        # Arrange
        monkeypatch.setattr('src.providers.execution.contracts.triggerable_withdrawals_bus.EL_REQUESTS_BATCH_SIZE', 2)
        contract = MagicMock()
        contract.functions.unprocessedIntentsCount.return_value.call.return_value = 3
        contract.functions.getWithdrawalIntents.return_value.call.side_effect = [
            [_intent(0xAA, 0), _intent(0xBB, 10**9)],
            [_intent(0xCC, 5 * 10**9)],
        ]

        # Act
        intents = TriggerableWithdrawalsBusContract.get_unprocessed_intents(contract, '0xblock')

        # Assert
        assert intents == [
            WithdrawalIntent(pubkey='0x' + 'aa' * 48, amount=Gwei(0)),
            WithdrawalIntent(pubkey='0x' + 'bb' * 48, amount=Gwei(10**9)),
            WithdrawalIntent(pubkey='0x' + 'cc' * 48, amount=Gwei(5 * 10**9)),
        ]
        assert contract.functions.getWithdrawalIntents.call_args_list == [call(0, 2), call(2, 2)]

    def test_get_unprocessed_intents__empty_queue__no_page_requested(self):
        contract = MagicMock()
        contract.functions.unprocessedIntentsCount.return_value.call.return_value = 0

        assert TriggerableWithdrawalsBusContract.get_unprocessed_intents(contract, '0xempty') == []
        contract.functions.getWithdrawalIntents.assert_not_called()

    def test_withdrawal_intent__zero_amount__is_full(self):
        assert WithdrawalIntent(pubkey='0x00', amount=Gwei(0)).is_full
        assert not WithdrawalIntent(pubkey='0x00', amount=Gwei(1)).is_full


@pytest.mark.unit
@pytest.mark.parametrize('allowed', [True, False])
def test_is_partial_withdrawals_allowed__module_state_config__returns_flag(allowed):
    contract = MagicMock()
    contract.functions.getStakingModuleStateConfig.return_value.call.return_value = SimpleNamespace(
        partialWithdrawalsAllowed=allowed
    )

    assert StakingRouterContract.is_partial_withdrawals_allowed(contract, 7, f'0x{allowed}') is allowed
    contract.functions.getStakingModuleStateConfig.assert_called_once_with(7)


@pytest.mark.unit
def test_triggerable_withdrawals_bus__called__returns_locator_value():
    contract = MagicMock()
    contract.functions.triggerableWithdrawalsBus.return_value.call.return_value = '0xBus'

    assert LidoLocatorContract.triggerable_withdrawals_bus(contract, '0xlocator') == '0xBus'


@pytest.mark.unit
def test_exit_iteration_chunk_eth__called__reads_exit_iteration_chunk_key():
    contract = MagicMock()
    contract._get.return_value = 32

    assert OracleDaemonConfigContract.exit_iteration_chunk_eth(contract, '0xconfig') == 32
    contract._get.assert_called_once_with('EXIT_ITERATION_CHUNK', '0xconfig')
