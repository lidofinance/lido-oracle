from unittest.mock import Mock, patch

import pytest

from src.modules.oracles.staking_modules.curated import entrypoint
from src.types import OracleModuleName


@pytest.mark.unit
class TestCuratedEntrypoint:
    def test_run__default__builds_web3_via_build_curated_module_web3(self):
        # Arrange
        web3 = Mock()

        with (
            patch.object(entrypoint, "log_startup") as log_startup,
            patch.object(entrypoint, "start_observability"),
            patch.object(entrypoint, "build_curated_module_web3", return_value=web3) as build_web3,
            patch.object(entrypoint, "CMPerformanceOracle") as oracle_cls,
            patch.object(entrypoint, "run_oracle_module") as run_oracle_module,
        ):
            # Act
            entrypoint.run()

        # Assert
        log_startup.assert_called_once_with(OracleModuleName.CM)
        build_web3.assert_called_once_with(OracleModuleName.CM)
        oracle_cls.assert_called_once_with(web3)
        run_oracle_module.assert_called_once_with(oracle_cls.return_value)
