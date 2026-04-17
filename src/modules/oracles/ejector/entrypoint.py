from modules.oracles.common.runtime import build_oracle_web3, run_oracle_module
from modules.oracles.ejector.ejector import Ejector
from runtime import log_startup, start_observability
from type_aliases import OracleModuleName


def run() -> None:
    log_startup(OracleModuleName.EJECTOR)
    start_observability()

    web3 = build_oracle_web3(OracleModuleName.EJECTOR)
    run_oracle_module(Ejector(web3))
