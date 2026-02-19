import pytest

from src import variables
from src.web3py.extensions.delegation import DelegationModule, DelegationNotConfiguredError, DelegateMismatchError


@pytest.mark.testnet
@pytest.mark.integration
class TestDelegationModule:
    def test_delegation_module_init__real_contract__validates_successfully(self, web3_integration, caplog):
        delegation_module = web3_integration.delegation

        assert delegation_module.is_enabled() is True
        assert delegation_module.delegation_address == variables.DELEGATION_CONTRACT_ADDRESS
        assert delegation_module.delegation_contract is not None
        assert any('DelegationModule initialized with contract' in message for message in caplog.messages)

    def test_delegation_module_init__real_contract__logs_validation_success(self, web3_integration, caplog):
        delegation_module = web3_integration.delegation

        assert delegation_module.is_enabled()
        assert any('Delegation contract validation passed' in message for message in caplog.messages)

    def test_wrap_call_for_delegation__real_contract__builds_execute_call(self, web3_integration, delegation_contract, caplog):
        delegation_module = web3_integration.delegation
        mock_target_call = delegation_contract.functions.admin()

        wrapped_call = delegation_module.wrap_call_for_delegation(mock_target_call)

        assert wrapped_call.address == delegation_contract.address
        assert wrapped_call.function_identifier == 'execute'
        assert any('Wrapping call for delegation' in message for message in caplog.messages)

    def test_is_enabled__real_contract__returns_true(self, web3_integration):
        delegation_module = web3_integration.delegation

        assert delegation_module.is_enabled() is True

    def test_validation_setup__real_delegatee__has_valid_delegatee(self, web3_integration):
        delegation_module = web3_integration.delegation
        current_delegatee = delegation_module.delegation_contract.get_delegatee()

        assert current_delegatee != '0x0000000000000000000000000000000000000000'
        assert delegation_module.is_enabled() is True

    def test_delegation_module_disabled__no_address__initialization_succeeds(self, caplog, monkeypatch):
        from web3 import Web3
        from src.web3py.extensions import FallbackProviderModule, DelegationModule
        from src.web3py.contract_tweak import tweak_w3_contracts

        monkeypatch.setattr(variables, 'DELEGATION_CONTRACT_ADDRESS', '')

        w3_no_delegation = Web3(
            FallbackProviderModule(
                variables.EXECUTION_CLIENT_URI,
                request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
                cache_allowed_requests=True,
            )
        )
        tweak_w3_contracts(w3_no_delegation)
        w3_no_delegation.attach_modules({
            'delegation': lambda: DelegationModule(w3_no_delegation, variables.DELEGATION_CONTRACT_ADDRESS),
        })

        delegation_module = w3_no_delegation.delegation

        assert delegation_module.is_enabled() is False
        assert delegation_module.delegation_address == ''
        assert delegation_module.delegation_contract is None
        assert any('DelegationModule initialized without contract - delegation disabled' in message for message in caplog.messages)

    def test_wrap_call_for_delegation__no_contract__raises_error(self, delegation_contract, monkeypatch):
        from web3 import Web3
        from src.web3py.extensions import FallbackProviderModule, DelegationModule
        from src.web3py.contract_tweak import tweak_w3_contracts

        monkeypatch.setattr(variables, 'DELEGATION_CONTRACT_ADDRESS', '')

        w3_no_delegation = Web3(
            FallbackProviderModule(
                variables.EXECUTION_CLIENT_URI,
                request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
                cache_allowed_requests=True,
            )
        )
        tweak_w3_contracts(w3_no_delegation)
        w3_no_delegation.attach_modules({
            'delegation': lambda: DelegationModule(w3_no_delegation, variables.DELEGATION_CONTRACT_ADDRESS),
        })

        delegation_module = w3_no_delegation.delegation
        mock_target_call = delegation_contract.functions.admin()

        with pytest.raises(RuntimeError, match="Delegation is not enabled"):
            delegation_module.wrap_call_for_delegation(mock_target_call)