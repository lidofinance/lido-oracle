import pytest


@pytest.mark.testnet
@pytest.mark.integration
class TestDelegationContract:
    def test_get_owner__real_contract__returns_valid_address(self, delegation_contract, caplog):
        owner_address = delegation_contract.get_owner()

        assert isinstance(owner_address, str)
        assert owner_address.startswith('0x')
        assert len(owner_address) == 42
        assert any('Call owner()' in message for message in caplog.messages)

    def test_get_delegate__real_contract__returns_valid_address(self, delegation_contract, caplog):
        delegate_address = delegation_contract.get_delegate()

        assert isinstance(delegate_address, str)
        assert delegate_address.startswith('0x')
        assert len(delegate_address) == 42
        assert any('Call getDelegate()' in message for message in caplog.messages)
