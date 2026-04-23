from modules.oracles.accounting.accounting import Accounting
from modules.oracles.common.runtime import build_oracle_web3, run_oracle_module
from runtime import log_startup, start_observability
from type_aliases import OracleModuleName


def run() -> None:
    log_startup(OracleModuleName.ACCOUNTING)
    start_observability()

    web3 = build_oracle_web3(OracleModuleName.ACCOUNTING)
    run_oracle_module(Accounting(web3))
