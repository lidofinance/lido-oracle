from unittest.mock import Mock, patch

import pytest

from src.modules.oracles.staking_modules.community_staking import entrypoint as csm_entrypoint
from src.modules.oracles.staking_modules.community_staking_0x02 import entrypoint as csm_0x02_entrypoint
from src.types import OracleModuleName


@pytest.mark.unit
class TestCommunityStakingEntrypoint:
    def test_run__called__builds_web3_via_build_community_module_web3(self):
        # Arrange
        web3 = Mock()

        with (
            patch.object(csm_entrypoint, "log_startup") as log_startup,
            patch.object(csm_entrypoint, "start_observability"),
            patch.object(csm_entrypoint, "build_community_module_web3", return_value=web3) as build_web3,
            patch.object(csm_entrypoint, "CSPerformanceOracle") as oracle_cls,
            patch.object(csm_entrypoint, "run_oracle_module") as run_oracle_module,
        ):
            # Act
            csm_entrypoint.run()

        # Assert
        log_startup.assert_called_once_with(OracleModuleName.CSM)
        build_web3.assert_called_once_with(OracleModuleName.CSM)
        oracle_cls.assert_called_once_with(web3)
        run_oracle_module.assert_called_once_with(oracle_cls.return_value)


@pytest.mark.unit
class TestCommunityStaking0x02Entrypoint:
    def test_run__called__builds_web3_via_build_community_module_web3(self):
        # Arrange
        web3 = Mock()

        with (
            patch.object(csm_0x02_entrypoint, "log_startup") as log_startup,
            patch.object(csm_0x02_entrypoint, "start_observability"),
            patch.object(csm_0x02_entrypoint, "build_community_module_web3", return_value=web3) as build_web3,
            patch.object(csm_0x02_entrypoint, "CSM0x02PerformanceOracle") as oracle_cls,
            patch.object(csm_0x02_entrypoint, "run_oracle_module") as run_oracle_module,
        ):
            # Act
            csm_0x02_entrypoint.run()

        # Assert
        log_startup.assert_called_once_with(OracleModuleName.CSM_0X02)
        build_web3.assert_called_once_with(OracleModuleName.CSM_0X02)
        oracle_cls.assert_called_once_with(web3)
        run_oracle_module.assert_called_once_with(oracle_cls.return_value)
