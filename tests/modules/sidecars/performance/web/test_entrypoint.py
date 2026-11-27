import logging
from unittest.mock import patch

import pytest

from src import runtime, variables
from src.modules.sidecars.performance.web import entrypoint
from src.types import OracleModuleName


@pytest.mark.unit
class TestRun:
    def test_run__startup__logs_masked_settings_before_serving(self, monkeypatch, caplog):
        monkeypatch.setattr(variables, 'PRIVATE_ENV_VARS', {'PERFORMANCE_DB_PASSWORD': 'db-password-1a2b3c4d'})
        logged_before_serve = []

        def serve():
            logged_before_serve.extend(
                record.msg for record in caplog.records if isinstance(record.msg, dict) and 'variables' in record.msg
            )

        with (
            caplog.at_level(logging.INFO, logger=runtime.logger.name),
            patch.object(entrypoint, 'serve', side_effect=serve) as serve_mock,
        ):
            entrypoint.run()

        serve_mock.assert_called_once_with()
        assert len(logged_before_serve) == 1
        startup = logged_before_serve[0]['variables']
        assert startup['module'] == OracleModuleName.PERFORMANCE_WEB_SERVER
        assert startup['PERFORMANCE_DB_PASSWORD'] == '***'
