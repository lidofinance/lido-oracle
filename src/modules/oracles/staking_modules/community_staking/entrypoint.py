from src.modules.oracles.common.runtime import build_staking_module_web3, run_oracle_module
from src.modules.oracles.staking_modules.community_staking.csm import CSPerformanceOracle
from src.runtime import log_startup, start_observability
from src.types import OracleModuleName


def run() -> None:
    log_startup(OracleModuleName.CSM)
    start_observability()

    web3 = build_staking_module_web3(OracleModuleName.CSM)
    run_oracle_module(CSPerformanceOracle(web3))
