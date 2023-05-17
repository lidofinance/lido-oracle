import logging
import time
from logging.handlers import QueueHandler
import pytest

from pytest import Item
from src.main import main
from multiprocessing import Process, Queue
from src.variables import EXECUTION_CLIENT_URI


@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(items: list[Item]):
    yield
    if any(not item.get_closest_marker("e2e") for item in items):
        for item in items:
            if item.get_closest_marker("e2e"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="e2e tests are take a lot of time " "and skipped if any other tests are selected"
                    )
                )


def worker_process(queue, module_name, execution_client_uri):
    import src.variables

    src.variables.EXECUTION_CLIENT_URI = [execution_client_uri]
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
