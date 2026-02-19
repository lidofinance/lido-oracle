import pytest


@pytest.mark.testnet
@pytest.mark.integration
class TestDelegationContract:

    def test_get_admin__real_contract__returns_valid_address(self, delegation_contract, caplog):
        admin_address = delegation_contract.get_admin()

        assert isinstance(admin_address, str)
        assert admin_address.startswith('0x')
        assert len(admin_address) == 42
        assert any('Call admin()' in message for message in caplog.messages)

    def test_get_delegatee__real_contract__returns_valid_address(self, delegation_contract, caplog):
        delegatee_address = delegation_contract.get_delegatee()

        assert isinstance(delegatee_address, str)
        assert delegatee_address.startswith('0x')
        assert len(delegatee_address) == 42
        assert any('Call delegatee()' in message for message in caplog.messages)
