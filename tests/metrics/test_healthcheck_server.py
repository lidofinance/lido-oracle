import unittest
from http import HTTPStatus
from io import BytesIO
from threading import Thread
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import requests
import requests_mock

from src.metrics.healthcheck_server import pulse, PulseRequestHandler, start_pulse_server
from src.variables import MAX_CYCLE_LIFETIME_IN_SECONDS, HEALTHCHECK_SERVER_PORT


class TestPulseFunction(unittest.TestCase):

    @requests_mock.Mocker()
    @patch('src.variables.HEALTHCHECK_SERVER_PORT', 8000)
    def test_pulse_success(self, mock_request):
        """Test that pulse successfully pings the healthcheck server."""
        mock_request.get(f'http://localhost:8000/pulse/', status_code=HTTPStatus.OK)

        with patch('logging.Logger.warning') as mock_warning:
            pulse()
            mock_warning.assert_not_called()

    @requests_mock.Mocker()
    @patch('src.variables.HEALTHCHECK_SERVER_PORT', 8000)
    def test_pulse_server_not_responding(self, mock_request):
        """Test that pulse logs a warning when the server is not responding."""
        mock_request.get(f'http://localhost:8000/pulse/', exc=requests.ConnectionError)

        with patch('logging.Logger.warning') as mock_warning:
            pulse()
            mock_warning.assert_called_once_with({'Healthcheck server is not responding.'})


class TestPulseRequestHandler(unittest.TestCase):

    def setUp(self):
        # Reset _last_pulse to current time before each test
        PulseRequestHandler._last_pulse = datetime.now()

    def _create_mock_request_handler(self, path):
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

    def test_update_last_pulse(self):
        """Test that update_last_pulse correctly updates the pulse time."""
        initial_time = PulseRequestHandler.get_last_pulse()
        PulseRequestHandler.update_last_pulse()
        updated_time = PulseRequestHandler.get_last_pulse()
        self.assertGreater(updated_time, initial_time, "The last pulse time should be updated to the current time.")

    def test_handler_response_ok(self):
        """Test that the handler responds with 200 OK when the last pulse is recent."""
        handler = self._create_mock_request_handler('/pulse/')
        PulseRequestHandler._last_pulse = datetime.now()  # Set last pulse to current time
        handler.do_GET()
        handler.wfile.seek(0)
        response = handler.wfile.read().decode('utf-8')
        self.assertIn('{"metrics": "ok", "reason": "ok"}', response)

    @patch('src.metrics.healthcheck_server.PulseRequestHandler.get_last_pulse')
    def test_handler_response_fail(self, mock_get_last_pulse):
        """Test that the handler responds with 503 when the last pulse is outdated."""
        # Set the last pulse to an outdated time
        mock_get_last_pulse.return_value = datetime.now() - timedelta(seconds=MAX_CYCLE_LIFETIME_IN_SECONDS + 1)

        handler = self._create_mock_request_handler('/pulse/')
        handler.do_GET()
        handler.wfile.seek(0)
        response = handler.wfile.read().decode('utf-8')
        self.assertIn('{"metrics": "fail", "reason": "timeout exceeded"}', response)


if __name__ == '__main__':
    unittest.main()
