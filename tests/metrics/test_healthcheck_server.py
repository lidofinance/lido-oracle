# pylint: disable=protected-access
import unittest
import pytest

from datetime import datetime, timedelta
from http import HTTPStatus
from io import BytesIO
from unittest.mock import patch, MagicMock

import requests
import responses

import src.metrics.healthcheck_server
from src.metrics.healthcheck_server import pulse, PulseRequestHandler
from src import variables


@pytest.mark.unit
class TestPulseFunction(unittest.TestCase):

    @responses.activate
    @patch('src.variables.HEALTHCHECK_SERVER_PORT', 8000)
    def test_pulse_success(self):
        """Test that pulse successfully pings the healthcheck server."""
        responses.get('http://localhost:8000/pulse/', status=HTTPStatus.OK)

        with patch('logging.Logger.warning') as mock_warning:
            pulse()
            mock_warning.assert_not_called()

    @responses.activate
    @patch('src.variables.HEALTHCHECK_SERVER_PORT', 8000)
    def test_pulse_server_not_responding(self):
        """Test that pulse logs a warning when the server is not responding."""
        responses.get('http://localhost:8000/pulse/', body=requests.ConnectionError())

        with patch('logging.Logger.warning') as mock_warning:
            pulse()
            mock_warning.assert_called_once_with({'Healthcheck server is not responding.'})


def _create_mock_request_handler(path):
    """Helper function to create a mock PulseRequestHandler."""
    # Mock socket with makefile to simulate the server environment
    mock_socket = MagicMock()
    mock_socket.makefile.return_value = BytesIO(b"GET " + path.encode('iso-8859-1') + b" HTTP/1.1\r\n")

    # Mock server
    mock_server = MagicMock()

    # Mock address
    client_address = ('127.0.0.1', 8080)

    # Initialize the handler with the mock socket and server
    handler = PulseRequestHandler(mock_socket, client_address, mock_server)
    handler.raw_requestline = b"GET " + path.encode('iso-8859-1') + b" HTTP/1.1\r\n"
    handler.rfile = BytesIO(handler.raw_requestline)
    handler.wfile = BytesIO()
    return handler


@pytest.mark.unit
class TestPulseRequestHandler(unittest.TestCase):
    def setUp(self):
        # Reset _last_pulse to current time before each test
        PulseRequestHandler._last_pulse = datetime.now()

    def test_handler_response_ok(self):
        """Test that the handler responds with 200 OK when the last pulse is recent."""
        handler = _create_mock_request_handler('/pulse/')
        PulseRequestHandler._last_pulse = datetime.now()  # Set last pulse to current time
        handler.do_GET()
        handler.wfile.seek(0)
        response = handler.wfile.read().decode('utf-8')
        self.assertIn('{"metrics": "ok", "reason": "ok"}', response)

    def test_handler_response_fail(self):
        """Test that the handler responds with 503 when the last pulse is outdated."""
        # Set the last pulse to an outdated time
        src.metrics.healthcheck_server._last_pulse = datetime.now() - timedelta(
            seconds=variables.MAX_CYCLE_LIFETIME_IN_SECONDS + 1
        )

        handler = _create_mock_request_handler('/smth/')
        handler.do_GET()
        handler.wfile.seek(0)
        response = handler.wfile.read().decode('utf-8')
        self.assertIn('{"metrics": "fail", "reason": "timeout exceeded"}', response)
