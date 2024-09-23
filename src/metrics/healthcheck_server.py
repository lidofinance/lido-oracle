import logging
import threading
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, HTTPServer

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from src import variables
from src.variables import MAX_CYCLE_LIFETIME_IN_SECONDS

logger = logging.getLogger(__name__)


def pulse():
    """Ping to healthcheck server that application is ok"""
    try:
        requests.get(f'http://localhost:{variables.HEALTHCHECK_SERVER_PORT}/pulse/', timeout=10)
    except RequestsConnectionError:
        logger.warning({'Healthcheck server is not responding.'})


class PulseRequestHandler(SimpleHTTPRequestHandler):
    """Request handler for Docker HEALTHCHECK"""

    # Encapsulate last pulse as a class variable
    _last_pulse = datetime.now()

    @classmethod
    def update_last_pulse(cls):
        """Update the last pulse time to the current time."""
        cls._last_pulse = datetime.now()

    @classmethod
    def get_last_pulse(cls) -> datetime:
        """Get the current last pulse time."""
        return cls._last_pulse

    def do_GET(self):
        """Handle GET requests for pulse checking."""
        if self.path == '/pulse/':
            self.update_last_pulse()

        if datetime.now() - self.get_last_pulse() > timedelta(seconds=MAX_CYCLE_LIFETIME_IN_SECONDS):
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"metrics": "fail", "reason": "timeout exceeded"}\n')
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"metrics": "ok", "reason": "ok"}\n')

    def log_request(self, *args, **kwargs):
        # Disable non-error logs
        pass


def start_pulse_server():  # pragma: no cover
    """
    This is simple server for bots without any API.
    If bot didn't call pulse for a while (5 minutes but should be changed individually)
    Docker healthcheck fails to do request
    """
    server = HTTPServer(('localhost', variables.HEALTHCHECK_SERVER_PORT), RequestHandlerClass=PulseRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
