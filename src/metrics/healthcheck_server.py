import threading
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, HTTPServer

import requests

from src import variables
from src.variables import MAX_CYCLE_LIFETIME_IN_SECONDS


_last_pulse = datetime.now()


def pulse():
    """Ping to healthcheck server that application is ok"""
    requests.get(f'http://localhost:{variables.HEALTHCHECK_SERVER_PORT}/pulse/', timeout=10)


class PulseRequestHandler(SimpleHTTPRequestHandler):
    """Request handler for Docker HEALTHCHECK"""
    def do_GET(self):
        global _last_pulse

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

    def log_request(self, *args, **kwargs):
        # Disable non-error logs
        pass


def start_pulse_server():
    """
    This is simple server for bots without any API.
    If bot didn't call pulse for a while (5 minutes but should be changed individually)
    healthcheck in docker returns 1 and bot will be restarted
    """
    server = HTTPServer(('localhost', variables.HEALTHCHECK_SERVER_PORT), RequestHandlerClass=PulseRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
