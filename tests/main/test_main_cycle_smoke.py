import logging
import logging.handlers
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import pytest

from src import variables
from src.main import main
from src.types import OracleModule


@pytest.mark.mainnet
@pytest.mark.integration
class TestIntegrationMainCycleSmoke:
    def run_main_with_logging(self, module_name, log_queue):
        queue_handler = logging.handlers.QueueHandler(log_queue)
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(queue_handler)

        main(module_name)

    @pytest.mark.parametrize(
        "module_name",
        [
            "accounting",
            "ejector",
            "csm",
        ],
    )
    def test_main_cycle_smoke__oracle_module__cycle_runs_successfully(
        self, monkeypatch, caplog, module_name: OracleModule
    ):
        monkeypatch.setattr(variables, 'DAEMON', False)
        monkeypatch.setattr(variables, 'CYCLE_SLEEP_IN_SECONDS', 0)

        port_offset = {"accounting": 0, "ejector": 100, "csm": 200}[module_name]
        monkeypatch.setattr(variables, 'PROMETHEUS_PORT', 19000 + port_offset)
        monkeypatch.setattr(variables, 'HEALTHCHECK_SERVER_PORT', 19001 + port_offset)

        monkeypatch.setattr("src.web3py.extensions.CSM.CONTRACT_LOAD_MAX_RETRIES", 3)
        monkeypatch.setattr("src.web3py.extensions.CSM.CONTRACT_LOAD_RETRY_DELAY", 0)

        # Mock CSM data collection to avoid CI timeout during processing thousands of epochs
        if module_name == "csm":

            def mock_collect_data(self, blockstamp):
                return True

            monkeypatch.setattr("src.modules.csm.csm.CSOracle.collect_data", mock_collect_data)

        manager = multiprocessing.Manager()
        log_queue = manager.Queue()
        listener = logging.handlers.QueueListener(log_queue, caplog.handler)
        listener.start()

        with ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.run_main_with_logging, module_name, log_queue)
            future.result()

        listener.stop()

        error_logs = [record for record in caplog.records if record.levelno >= logging.ERROR]
        assert not error_logs, f"Found error logs: {[record.message for record in error_logs]}"
