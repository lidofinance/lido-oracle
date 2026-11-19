import unittest
from unittest.mock import MagicMock, mock_open, patch

import pytest
from web3 import Web3

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
