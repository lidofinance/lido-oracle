from modules.oracles.common.runtime import build_staking_module_web3, run_oracle_module
from modules.oracles.staking_modules.curated.cm import CMPerformanceOracle
from runtime import log_startup, start_observability
from type_aliases import OracleModuleName


def run() -> None:
    log_startup(OracleModuleName.CM)
    start_observability()

    web3 = build_staking_module_web3(OracleModuleName.CM)
    run_oracle_module(CMPerformanceOracle(web3))
