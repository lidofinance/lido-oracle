import logging
import time
from logging.handlers import QueueHandler
from multiprocessing import Process, Queue

import pytest

from src import variables
from src.main import main
from src.variables import EXECUTION_CLIENT_URI


def worker_process(queue, module_name, execution_client_uri):
    variables.EXECUTION_CLIENT_URI = [execution_client_uri]
    qh = QueueHandler(queue)
    root = logging.getLogger()
    root.addHandler(qh)
    main(module_name)


@pytest.fixture(scope="session", params=EXECUTION_CLIENT_URI)
def execution_client_uri(request):
    return request.param


@pytest.fixture
def start_accounting(caplog, execution_client_uri):
    queue = Queue()
    listener = logging.handlers.QueueListener(queue, caplog.handler)
    listener.start()

    worker = Process(target=worker_process, args=(queue, "accounting", execution_client_uri))
    worker.start()
    yield
    worker.terminate()


def wait_for_message_appeared(caplog, message, timeout=600):
    start_time = time.time()
    while True:
        if message in caplog.messages:
            return
        if time.time() - start_time > timeout:
            break
        time.sleep(1)
    raise AssertionError(f"Message {message} not found in logs")


@pytest.mark.e2e
def test_app(start_accounting, caplog):
    wait_for_message_appeared(caplog, "{'msg': 'Run module as daemon.'}", timeout=10)
    wait_for_message_appeared(caplog, "{'msg': 'Check if main data was submitted.', 'value': False}")
    wait_for_message_appeared(caplog, "{'msg': 'Check if contract could accept report.', 'value': True}")
    wait_for_message_appeared(caplog, "{'msg': 'Execute module.'}")
    wait_for_message_appeared(caplog, "{'msg': 'Checking bunker mode'}", timeout=1800)
    wait_for_message_appeared(caplog, "{'msg': 'Send report hash. Consensus version: [1]'}")
