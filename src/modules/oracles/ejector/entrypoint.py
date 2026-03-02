from src.modules.oracles.common.runtime import build_oracle_web3, run_oracle_module
from src.modules.oracles.ejector.ejector import Ejector
from src.runtime import log_startup, start_observability
from src.types import OracleModuleName


def run() -> None:
    log_startup(OracleModuleName.EJECTOR)
    start_observability()

    web3 = build_oracle_web3()
    run_oracle_module(Ejector(web3))
