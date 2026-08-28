from unittest.mock import MagicMock, Mock

import pytest

from src import variables
from src.web3py.extensions.delegation import DelegationModule


DUMMY_ADDRESS = '0x' + '12' * 20
ORACLE_ADDRESS = '0x' + 'ab' * 20
ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'


@pytest.mark.unit
class TestDelegationModule:
    @pytest.fixture
    def mock_w3(self):
        w3 = MagicMock()
        w3.eth.contract.return_value = Mock()
        w3.eth.contract.return_value.address = DUMMY_ADDRESS
        return w3

    @pytest.fixture
    def mock_account(self):
        account = Mock()
        account.address = ORACLE_ADDRESS
        return account

    def test_init__no_delegation_address__disabled(self, mock_w3, caplog):
        module = DelegationModule(mock_w3, delegation_address=None)

        assert module.delegation_contract is None
        assert module.delegation_address is None
        assert module.is_enabled() is False
        assert 'delegation disabled' in caplog.text

    def test_init__valid_delegation_setup__enabled(self, mock_w3, mock_account, monkeypatch, caplog):
        monkeypatch.setattr(variables, 'ACCOUNT', mock_account)
        mock_w3.eth.contract.return_value.get_delegatee.return_value = ORACLE_ADDRESS
        mock_w3.eth.contract.return_value.get_admin.return_value = DUMMY_ADDRESS

        module = DelegationModule(mock_w3, delegation_address=DUMMY_ADDRESS)

        assert module.delegation_contract is not None
        assert module.is_enabled() is True
        assert 'Delegation contract validation passed' in caplog.text

    def test_init__no_account__skips_validation(self, mock_w3, monkeypatch, caplog):
        monkeypatch.setattr(variables, 'ACCOUNT', None)

        module = DelegationModule(mock_w3, delegation_address=DUMMY_ADDRESS)

        assert module.delegation_contract is not None
        assert 'Skipping delegation validation' in caplog.text

    def test_init__delegatee_is_zero_address__raises_not_configured_error(self, mock_w3, mock_account, monkeypatch):
        monkeypatch.setattr(variables, 'ACCOUNT', mock_account)
        mock_w3.eth.contract.return_value.get_delegatee.return_value = ZERO_ADDRESS

        with pytest.raises(DelegationModule.NotConfiguredError):
            DelegationModule(mock_w3, delegation_address=DUMMY_ADDRESS)

    def test_init__delegatee_mismatch__raises_mismatch_error(self, mock_w3, mock_account, monkeypatch):
        monkeypatch.setattr(variables, 'ACCOUNT', mock_account)
        other_address = '0x' + 'cc' * 20
        mock_w3.eth.contract.return_value.get_delegatee.return_value = other_address

        with pytest.raises(DelegationModule.DelegateMismatchError):
            DelegationModule(mock_w3, delegation_address=DUMMY_ADDRESS)

    def test_wrap_call_for_delegation__disabled_delegation__raises_runtime_error(self, mock_w3):
        module = DelegationModule(mock_w3, delegation_address=None)
        target_call = Mock()

        with pytest.raises(RuntimeError, match="Delegation is not enabled"):
            module.wrap_call_for_delegation(target_call)

    def test_wrap_call_for_delegation__correct_encoding__returns_delegation_execute_call(
        self, mock_w3, mock_account, monkeypatch
    ):
        # Arrange
        monkeypatch.setattr(variables, 'ACCOUNT', mock_account)
        mock_w3.eth.contract.return_value.get_delegatee.return_value = ORACLE_ADDRESS
        mock_w3.eth.contract.return_value.get_admin.return_value = DUMMY_ADDRESS

        module = DelegationModule(mock_w3, delegation_address=DUMMY_ADDRESS)

        # Mock target contract call
        target_call = Mock()
        target_call.address = '0x1234567890123456789012345678901234567890'
        target_call.contract_abi = []
        target_call.fn_name = 'testMethod'
        target_call.args = [123, 'test']

        # Mock contract for encoding
        mock_target_contract = Mock()
        mock_target_contract.encode_abi.return_value = '0xabcdef123456'
        mock_w3.eth.contract.return_value = mock_target_contract

        # Mock delegation contract execute method
        mock_delegation_execute = Mock()
        module.delegation_contract.execute.return_value = mock_delegation_execute

        # Act
        result = module.wrap_call_for_delegation(target_call)

        # Assert
        expected_calldata = bytes.fromhex('abcdef123456')
        module.delegation_contract.execute.assert_called_once_with(
            '0x1234567890123456789012345678901234567890', expected_calldata
        )
        assert result == mock_delegation_execute

        # Verify encoding was called with correct parameters
        mock_target_contract.encode_abi.assert_called_once_with('testMethod', [123, 'test'])
