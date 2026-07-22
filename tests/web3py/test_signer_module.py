from unittest.mock import MagicMock, Mock

import pytest

from src.web3py.extensions.signer import SignerModule


ACCOUNT_1_ADDRESS = '0x' + '11' * 20
ACCOUNT_2_ADDRESS = '0x' + '22' * 20
DELEGATION_CONTRACT_ADDRESS = '0x' + '33' * 20
UNRELATED_ADDRESS = '0x' + '99' * 20


def make_account(address):
    account = Mock()
    account.address = address
    return account


def make_w3(delegate=None):
    """Web3 mock whose contract factory returns a delegation contract mock with a fixed delegate."""
    w3 = MagicMock()

    def contract(address=None, **kwargs):
        contract_mock = Mock()
        contract_mock.address = address
        contract_mock.get_delegate.return_value = delegate
        return contract_mock

    w3.eth.contract = Mock(side_effect=contract)
    return w3


@pytest.mark.unit
class TestSignerModuleInit:
    def test_init__no_delegation_contract_address__delegation_contract_is_none(self):
        module = SignerModule(make_w3(), make_account(ACCOUNT_1_ADDRESS), None, None)

        assert module.delegation_contract is None
        assert module.active_signer is None
        assert module.is_delegated is False

    def test_init__delegation_contract_address_set__builds_contract(self, caplog):
        w3 = make_w3()

        module = SignerModule(w3, make_account(ACCOUNT_1_ADDRESS), None, DELEGATION_CONTRACT_ADDRESS)

        assert module.delegation_contract is not None
        assert module.delegation_contract.address == DELEGATION_CONTRACT_ADDRESS
        w3.eth.contract.assert_called_once()
        assert 'Initialize delegation contract.' in caplog.text

    def test_init__no_accounts_configured__dry_defaults(self):
        module = SignerModule(make_w3(), None, None, None)

        assert module.active_signer is None
        assert module.is_delegated is False


@pytest.mark.unit
class TestProcessMembers:
    def test_process_members__account_1_is_plain_member__activates_account_1(self):
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        module = SignerModule(make_w3(), account_1, None, None)

        module.process_members([ACCOUNT_1_ADDRESS])

        assert module.active_signer is account_1
        assert module.is_delegated is False

    def test_process_members__account_2_is_plain_member__activates_account_2(self):
        """Regression test: a previous version activated account_1 even when account_2 matched."""
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        account_2 = make_account(ACCOUNT_2_ADDRESS)
        module = SignerModule(make_w3(), account_1, account_2, None)

        module.process_members([ACCOUNT_2_ADDRESS])

        assert module.active_signer is account_2
        assert module.is_delegated is False

    def test_process_members__both_accounts_are_plain_members__earlier_in_member_list_wins(self):
        # In practice, we should not get it in production.
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        account_2 = make_account(ACCOUNT_2_ADDRESS)
        module = SignerModule(make_w3(), account_1, account_2, None)

        module.process_members([ACCOUNT_2_ADDRESS, ACCOUNT_1_ADDRESS])
        assert module.active_signer is account_2

        module.process_members([ACCOUNT_1_ADDRESS, ACCOUNT_2_ADDRESS])
        assert module.active_signer is account_1

    def test_process_members__empty_member_list__active_signer_none_and_warns(self, caplog):
        """E.g. the first frame hasn't started yet and HashConsensus has no members configured."""
        module = SignerModule(make_w3(), make_account(ACCOUNT_1_ADDRESS), None, None)

        module.process_members([])

        assert module.active_signer is None
        assert module.is_delegated is False
        assert 'None of the configured accounts is an active member.' in caplog.text

    def test_process_members__no_configured_account_is_member__active_signer_none_and_warns(self, caplog):
        module = SignerModule(make_w3(), make_account(ACCOUNT_1_ADDRESS), None, None)

        module.process_members([UNRELATED_ADDRESS])

        assert module.active_signer is None
        assert module.is_delegated is False
        assert 'None of the configured accounts is an active member.' in caplog.text

    def test_process_members__no_delegation_contract_configured__does_not_crash(self):
        """Regression test: a previous version crashed with AttributeError whenever no
        delegation contract was configured - the common, delegation-disabled case."""
        module = SignerModule(make_w3(), make_account(ACCOUNT_1_ADDRESS), None, None)

        module.process_members([UNRELATED_ADDRESS, ACCOUNT_1_ADDRESS])

        assert module.active_signer.address == ACCOUNT_1_ADDRESS

    def test_process_members__delegation_contract_member_delegate_is_account_1__activates_account_1_delegated(self):
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        module = SignerModule(make_w3(delegate=ACCOUNT_1_ADDRESS), account_1, None, DELEGATION_CONTRACT_ADDRESS)

        module.process_members([DELEGATION_CONTRACT_ADDRESS])

        assert module.active_signer is account_1
        assert module.is_delegated is True

    def test_process_members__delegation_contract_member_delegate_is_account_2__activates_account_2_delegated(self):
        """Regression test: a previous version activated account_1 even when the delegate
        matched account_2's address."""
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        account_2 = make_account(ACCOUNT_2_ADDRESS)
        module = SignerModule(make_w3(delegate=ACCOUNT_2_ADDRESS), account_1, account_2, DELEGATION_CONTRACT_ADDRESS)

        module.process_members([DELEGATION_CONTRACT_ADDRESS])

        assert module.active_signer is account_2
        assert module.is_delegated is True

    def test_process_members__delegate_matches_no_configured_account__active_signer_none_and_warns(self, caplog):
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        module = SignerModule(make_w3(delegate=UNRELATED_ADDRESS), account_1, None, DELEGATION_CONTRACT_ADDRESS)

        module.process_members([DELEGATION_CONTRACT_ADDRESS])

        assert module.active_signer is None
        assert module.is_delegated is False
        assert 'matches none of the configured accounts' in caplog.text

    def test_process_members__delegation_contract_and_plain_account_both_members__delegation_wins(self):
        """Mid-rotation transitional state: prefer the delegation contract identity."""
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        module = SignerModule(make_w3(delegate=ACCOUNT_1_ADDRESS), account_1, None, DELEGATION_CONTRACT_ADDRESS)

        module.process_members([ACCOUNT_1_ADDRESS, DELEGATION_CONTRACT_ADDRESS])

        assert module.active_signer is account_1
        assert module.is_delegated is True

    def test_process_members__previously_active_signer_no_longer_a_member__resets_to_none(self):
        """Correctness fix: state must not leak across cycles once an identity stops being active."""
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        module = SignerModule(make_w3(), account_1, None, None)

        module.process_members([ACCOUNT_1_ADDRESS])
        assert module.active_signer is account_1

        module.process_members([UNRELATED_ADDRESS])

        assert module.active_signer is None
        assert module.is_delegated is False

    def test_process_members__was_delegated_then_becomes_plain_eoa__is_delegated_flips_to_false(self):
        account_1 = make_account(ACCOUNT_1_ADDRESS)
        module = SignerModule(make_w3(delegate=ACCOUNT_1_ADDRESS), account_1, None, DELEGATION_CONTRACT_ADDRESS)

        module.process_members([DELEGATION_CONTRACT_ADDRESS])
        assert module.is_delegated is True

        module.process_members([ACCOUNT_1_ADDRESS])

        assert module.is_delegated is False
        assert module.active_signer is account_1


@pytest.mark.unit
class TestWrapCallForDelegation:
    def test_wrap_call_for_delegation__no_delegation_contract__raises_runtime_error(self):
        module = SignerModule(make_w3(), make_account(ACCOUNT_1_ADDRESS), None, None)

        with pytest.raises(RuntimeError, match="Delegation is not enabled"):
            module.wrap_call_for_delegation(Mock())

    def test_wrap_call_for_delegation__correct_encoding__returns_delegation_execute_call(self):
        # Arrange
        w3 = make_w3()
        module = SignerModule(w3, make_account(ACCOUNT_1_ADDRESS), None, DELEGATION_CONTRACT_ADDRESS)

        mock_delegation_execute = Mock()
        module.delegation_contract.execute.return_value = mock_delegation_execute

        target_call = Mock()
        target_call.address = '0x1234567890123456789012345678901234567890'
        target_call.contract_abi = []
        target_call.fn_name = 'testMethod'
        target_call.args = [123, 'test']

        mock_target_contract = Mock()
        mock_target_contract.encode_abi.return_value = '0xabcdef123456'
        w3.eth.contract = Mock(return_value=mock_target_contract)

        # Act
        result = module.wrap_call_for_delegation(target_call)

        # Assert
        expected_calldata = bytes.fromhex('abcdef123456')
        module.delegation_contract.execute.assert_called_once_with(
            '0x1234567890123456789012345678901234567890', expected_calldata
        )
        assert result == mock_delegation_execute
        mock_target_contract.encode_abi.assert_called_once_with('testMethod', [123, 'test'])
