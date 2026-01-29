import logging
import logging.handlers
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import pytest

from src import variables
from src.main import main
from src.types import OracleModuleName


@pytest.mark.mainnet
@pytest.mark.integration
class TestIntegrationMainCycleSmoke:
    def run_main_with_logging(self, module_name, log_queue):
        queue_handler = logging.handlers.QueueHandler(log_queue)
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(queue_handler)

        variables.DAEMON = False
        variables.CYCLE_SLEEP_IN_SECONDS = 0

        if module_name is OracleModuleName.CSM:
            variables.PERFORMANCE_COLLECTOR_URI = ["http://localhost:9020"]

            from src.web3py.extensions.staking_module import StakingModuleContracts

            StakingModuleContracts.CONTRACT_LOAD_MAX_RETRIES = 3
            StakingModuleContracts.CONTRACT_LOAD_RETRY_DELAY = 0

            from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle

            CSPerformanceOracle._collect_data = lambda self: True
            CSPerformanceOracle._on_shutdown = lambda self: None

            from src.providers.performance.client import PerformanceClient

            PerformanceClient.is_range_available = lambda *args, **kwargs: True
            PerformanceClient.get_epochs_demand = lambda *args, **kwargs: None
            PerformanceClient.post_epochs_demand = lambda *args, **kwargs: None
            PerformanceClient.delete_epochs_demand = lambda *args, **kwargs: None

        main(module_name)

    @pytest.mark.parametrize(
        "module_name",
        [
            OracleModuleName.ACCOUNTING,
            OracleModuleName.EJECTOR,
            OracleModuleName.CSM,
            # TODO: Enable when CM module is on mainnet
            # OracleModuleName.CM
        ],
    )
    def test_main_cycle_smoke__oracle_module__cycle_runs_successfully(self, caplog, module_name: OracleModuleName):
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
