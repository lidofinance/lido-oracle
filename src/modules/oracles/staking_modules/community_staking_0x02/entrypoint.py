from src.modules.oracles.common.runtime import build_staking_module_web3, run_oracle_module
from src.modules.oracles.staking_modules.community_staking_0x02.csm_0x02 import CSM0x02PerformanceOracle
from src.runtime import log_startup, start_observability
from src.types import OracleModuleName


def run() -> None:
    log_startup(OracleModuleName.CSM_0X02)
    start_observability()

    web3 = build_staking_module_web3(OracleModuleName.CSM_0X02)
    run_oracle_module(CSM0x02PerformanceOracle(web3))
