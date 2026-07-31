import faulthandler
import logging
import logging.handlers
import multiprocessing
import os
import signal
import time
from typing import cast

import pytest

from src import variables
from src.main import main
from src.modules.common.daemon_module import DaemonModule
from src.modules.oracles.common.consensus import ConsensusModule
from src.types import OracleModuleName


# Most cycles end within seconds because the module is not reportable, but a reportable frame on
# mainnet has taken over 6 minutes. This is a deadlock detector, not a latency budget, so keep it
# loose enough that a slow beacon node cannot trip it.
CYCLE_TIMEOUT = 15 * 60


@pytest.mark.mainnet
@pytest.mark.integration
class TestIntegrationMainCycleSmoke:
    def run_main_with_logging(self, module_name, log_queue):
        # Let the parent ask for a stack dump when the cycle overruns CYCLE_TIMEOUT. pytest runs
        # without output capture, so the dump lands directly in the CI log.
        faulthandler.register(signal.SIGUSR1)

        queue_handler = logging.handlers.QueueHandler(log_queue)
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(queue_handler)

        variables.DAEMON = False
        variables.CYCLE_SLEEP_IN_SECONDS = 0

        # Use last finalized instead of head slot for avoiding calls with non-existent block at the moment of cycle
        ConsensusModule._get_latest_blockstamp = lambda self: cast(DaemonModule, self)._receive_last_finalized_slot()

        if module_name is OracleModuleName.CSM:
            variables.PERFORMANCE_COLLECTOR_URI = ["http://localhost:9020"]

            from src.web3py.extensions.staking_module import StakingModuleContracts

            StakingModuleContracts.CONTRACT_LOAD_MAX_RETRIES = 3
            StakingModuleContracts.CONTRACT_LOAD_RETRY_DELAY = 0

            from src.modules.oracles.staking_modules.common.state import State
            from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle

            CSPerformanceOracle._prepare_duties_state = lambda self, blockstamp: State(
                blockstamp.ref_epoch, blockstamp.ref_epoch, 1
            )

            from src.providers.performance.client import PerformanceClient

            # Report the whole requested range as stored, so the oracle sees the data as available
            PerformanceClient.get_stored_epochs_count = lambda self, from_epoch, to_epoch: to_epoch - from_epoch + 1
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
        ctx = multiprocessing.get_context('fork')
        manager = ctx.Manager()
        log_queue = manager.Queue()
        listener = logging.handlers.QueueListener(log_queue, caplog.handler)
        listener.start()

        # A bare Process rather than ProcessPoolExecutor: the pool joins its workers on shutdown and
        # again from an atexit hook, so a single stuck cycle hangs the whole pytest run instead of
        # failing this test. Owning the process lets us put a hard bound on it.
        process = ctx.Process(target=self.run_main_with_logging, args=(module_name, log_queue))
        process.start()
        timed_out = False

        try:
            process.join(CYCLE_TIMEOUT)
            if process.is_alive():
                timed_out = True
                os.kill(cast(int, process.pid), signal.SIGUSR1)  # dump where the cycle is stuck
                time.sleep(1)  # give faulthandler a moment to flush before the process dies
                process.kill()
                process.join()
        finally:
            # Drain the records the child queued, then stop the manager process hosting the queue.
            # Both must happen even when the cycle fails, or the leftovers keep pytest from exiting.
            listener.stop()
            manager.shutdown()

        assert not timed_out, f"{module_name} cycle did not finish within {CYCLE_TIMEOUT}s"
        assert process.exitcode == 0, f"{module_name} cycle exited with code {process.exitcode}"

        error_logs = [record for record in caplog.records if record.levelno >= logging.ERROR]
        assert not error_logs, f"Found error logs: {[record.message for record in error_logs]}"
