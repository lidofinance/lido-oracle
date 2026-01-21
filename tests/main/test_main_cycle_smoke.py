import logging

import pytest

from src import variables
from src.main import main
from src.types import OracleModule


@pytest.mark.mainnet
@pytest.mark.integration
class TestIntegrationMainCycleSmoke:
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
        monkeypatch.setattr("src.web3py.extensions.CSM.CONTRACT_LOAD_MAX_RETRIES", 3)
        monkeypatch.setattr("src.web3py.extensions.CSM.CONTRACT_LOAD_RETRY_DELAY", 0)

        # Mock CSM data collection to avoid CI timeout during processing thousands of epochs
        if module_name == "csm":

            def mock_collect_data(self, blockstamp):
                return True

            monkeypatch.setattr("src.modules.csm.csm.CSOracle.collect_data", mock_collect_data)

        # Run main directly - caplog will capture logs automatically
        with caplog.at_level(logging.DEBUG):
            main(module_name)

        error_logs = [record for record in caplog.records if record.levelno >= logging.ERROR]
        assert not error_logs, f"Found error logs: {[record.message for record in error_logs]}"
