import unittest
import pytest
from unittest.mock import patch, MagicMock, mock_open

from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


@pytest.mark.unit
class TestContractInterface(unittest.TestCase):
    def setUp(self):
        # Set up a mock Web3 instance
        self.w3 = MagicMock(spec=Web3)

    @patch('builtins.open', new_callable=mock_open, read_data='{"abi": "mock_abi"}')
    def test_load_abi(self, mock_open_file):
        """Test the load_abi method to ensure it loads the ABI from a file."""
        abi_file = 'test_abi.json'

        # Call the method
        abi = ContractInterface.load_abi(abi_file)

        # Verify the file was opened and the ABI was loaded
        mock_open_file.assert_called_once_with(abi_file)
        self.assertEqual(abi, {"abi": "mock_abi"}, "ABI should match the mocked data")

    def test_factory_missing_abi_path(self):
        """Test the factory method raises an exception when abi_path is not set."""

        # Define a test class without abi_path
        class TestContractWithoutAbiPath(ContractInterface):
            abi_path = None

        # Verify it raises AttributeError
        with self.assertRaises(AttributeError):
            TestContractWithoutAbiPath.factory(self.w3)

    @patch('src.providers.execution.base_interface.ContractInterface.w3')
    def test_is_deployed_contract_exists(self, mock_w3):
        """Test the is_deployed method when the contract is deployed."""
        mock_w3.eth.get_code.return_value = b'\x01'  # Simulate contract code present

        # Define an instance of a contract
        test_contract = ContractInterface(address="0x0000000000000000000000000000000000000000")
        block = MagicMock(spec=BlockIdentifier)

        # Check that contract is deployed
        result = test_contract.is_deployed(block)
        self.assertTrue(result, "Contract should be detected as deployed")

        # Check if get_code was called with the correct arguments
        mock_w3.eth.get_code.assert_called_once_with(test_contract.address, block_identifier=block)

    @patch('src.providers.execution.base_interface.ContractInterface.w3')
    def test_is_deployed_contract_not_exists(self, mock_w3):
        """Test the is_deployed method when the contract is not deployed."""
        mock_w3.eth.get_code.return_value = b''  # Simulate no contract code present

        # Define an instance of a contract
        test_contract = ContractInterface(address="0x0000000000000000000000000000000000000000")
        block = MagicMock(spec=BlockIdentifier)

        # Check that contract is not deployed
        result = test_contract.is_deployed(block)
        self.assertFalse(result, "Contract should be detected as not deployed")

        # Check if get_code was called with the correct arguments
        mock_w3.eth.get_code.assert_called_once_with(test_contract.address, block_identifier=block)
