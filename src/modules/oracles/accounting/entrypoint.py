from src.modules.oracles.accounting.accounting import Accounting
from src.modules.oracles.common.runtime import build_oracle_web3, run_oracle_module
from src.runtime import log_startup, start_observability
from src.types import OracleModule


def run() -> None:
    log_startup(OracleModule.ACCOUNTING)
    start_observability()

    web3 = build_oracle_web3()
    run_oracle_module(Accounting(web3))
