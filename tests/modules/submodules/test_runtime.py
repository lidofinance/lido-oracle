from unittest.mock import Mock, patch

import pytest

from src import variables
from src.modules.oracles.common import runtime
from src.types import OracleModuleName
from src.web3py.extensions import CuratedModuleContracts, StakingModuleContracts


@pytest.mark.unit
class TestBuildModuleWeb3:
    @pytest.fixture(autouse=True)
    def web3_deps(self, monkeypatch):
        monkeypatch.setattr(variables, "PERFORMANCE_COLLECTOR_URI", ["http://collector"])
        self.web3 = Mock()

        with (
            patch.object(runtime, "_build_web3_base", return_value=self.web3) as build_base,
            patch.object(runtime, "PerformanceClientModule"),
            patch.object(runtime, "IPFS"),
            patch.object(runtime, "ipfs_providers"),
            patch.object(runtime, "init_metrics"),
            patch.object(runtime, "init_basic_metrics"),
        ):
            self.build_base = build_base
            yield

    @pytest.mark.parametrize(
        "module_name",
        [OracleModuleName.CSM, OracleModuleName.CSM_0X02, OracleModuleName.CHECK],
    )
    def test_build_community_module_web3__module_name__attaches_staking_module_contracts(self, module_name):
        runtime.build_community_module_web3(module_name)

        attached = self.web3.attach_modules.call_args.args[0]
        assert attached["staking_module"] is StakingModuleContracts
        assert self.build_base.call_args.args[1] == module_name

    @pytest.mark.parametrize("module_name", [OracleModuleName.CM, OracleModuleName.CHECK])
    def test_build_curated_module_web3__module_name__attaches_curated_contracts_with_given_label(self, module_name):
        runtime.build_curated_module_web3(module_name)

        attached = self.web3.attach_modules.call_args.args[0]
        assert attached["staking_module"] is CuratedModuleContracts
        assert self.build_base.call_args.args[1] == module_name
