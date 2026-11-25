import logging
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError

from src import variables
from src.variables import MAX_CYCLE_LIFETIME_IN_SECONDS


_last_pulse = datetime.now()
_ready = threading.Event()
logger = logging.getLogger(__name__)


def mark_ready() -> None:
    """The module finished its initialization: `/ready` answers 200 from now on."""
    _ready.set()


def pulse():
    """Ping to healthcheck server that application is ok"""
    try:
        requests.get(f'http://localhost:{variables.HEALTHCHECK_SERVER_PORT}/pulse/', timeout=10)
    except RequestsConnectionError:
        logger.warning({'Healthcheck server is not responding.'})


class PulseRequestHandler(SimpleHTTPRequestHandler):
    """Request handler for the Docker HEALTHCHECK (answers by the pulse age) and for the `/ready` readiness path"""

    def do_GET(self):
        global _last_pulse

        if self.path.rstrip('/') == '/ready':
            self._respond_readiness()
            return

        if self.path == '/pulse/':
            _last_pulse = datetime.now()

        if datetime.now() - _last_pulse > timedelta(seconds=MAX_CYCLE_LIFETIME_IN_SECONDS):
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"metrics": "fail", "reason": "timeout exceeded"}\n')
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"metrics": "ok", "reason": "ok"}\n')

    def _respond_readiness(self):
        """Readiness for an orchestrator: 503 while the module starts, 200 after. The pulse age is liveness only."""
        ready = _ready.is_set()
        self.send_response(200 if ready else 503)
        self.end_headers()
        self.wfile.write(b'{"ready": true}\n' if ready else b'{"ready": false}\n')

    def log_request(self, *args, **kwargs):
        # Disable non-error logs
        pass


def start_pulse_server():
    """
    This is simple server for bots without any API.
    If bot didn't call pulse for a while (5 minutes but should be changed individually)
    Docker healthcheck fails to do request
    """
    server = HTTPServer(('localhost', variables.HEALTHCHECK_SERVER_PORT), RequestHandlerClass=PulseRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
