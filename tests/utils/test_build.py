import unittest
import pytest
from unittest.mock import patch, mock_open
import json

from src.utils.build import get_build_info, UNKNOWN_BUILD_INFO


@pytest.mark.unit
class TestGetBuildInfo(unittest.TestCase):
    @patch(
        'builtins.open', new_callable=mock_open, read_data='{"version": "1.0.0", "branch": "main", "commit": "abc123"}'
    )
    def test_get_build_info_success(self, mock_open_file):
        """Test that get_build_info successfully reads from the JSON file."""
        expected_build_info = {"version": "1.0.0", "branch": "main", "commit": "abc123"}

        # Call the function
        build_info = get_build_info()

        # Assertions
        mock_open_file.assert_called_once_with("./build-info.json", "r")
        self.assertEqual(build_info, expected_build_info, "Build info should match the data from the file")

    def test_get_build_info_file_not_exists(self):
        """Test that get_build_info returns UNKNOWN_BUILD_INFO when the file does not exist."""
        build_info = get_build_info()

        # Assertions
        self.assertEqual(build_info, UNKNOWN_BUILD_INFO, "Should return UNKNOWN_BUILD_INFO when file doesn't exist")

    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data='invalid json')
    def test_get_build_info_json_decode_error(self, mock_open_file, mock_exists):
        """Test that get_build_info returns UNKNOWN_BUILD_INFO when there is a JSONDecodeError."""
        # Simulate a JSONDecodeError by providing invalid JSON in the file
        with patch('json.load', side_effect=json.JSONDecodeError("Expecting value", "document", 0)):
            build_info = get_build_info()

        # Assertions
        mock_open_file.assert_called_once_with("./build-info.json", "r")
        self.assertEqual(build_info, UNKNOWN_BUILD_INFO, "Should return UNKNOWN_BUILD_INFO when JSON decode fails")
