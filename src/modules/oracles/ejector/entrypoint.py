from src.modules.oracles.common.runtime import OracleWeb3Config, build_oracle_web3, run_oracle_module
from src.modules.oracles.ejector.ejector import Ejector
from src.runtime import log_startup, start_observability
from src.types import OracleModule


def run() -> None:
    log_startup(OracleModule.EJECTOR)
    start_observability()

    web3 = build_oracle_web3(OracleWeb3Config())
    run_oracle_module(Ejector(web3))
