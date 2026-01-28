from src.modules.oracles.common.runtime import build_staking_module_web3, run_oracle_module
from src.modules.oracles.staking_modules.curated.cm import CMPerformanceOracle
from src.runtime import log_startup, start_observability
from src.types import OracleModule


def run() -> None:
    log_startup(OracleModule.CM)
    start_observability()

    web3 = build_staking_module_web3()
    run_oracle_module(CMPerformanceOracle(web3))
