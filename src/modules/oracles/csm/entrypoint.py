from src.modules.oracles.common.runtime import OracleWeb3Config, build_oracle_web3, run_oracle_module
from src.modules.oracles.csm.csm import CSOracle
from src.runtime import log_startup, start_observability
from src.types import OracleModule


def run() -> None:
    log_startup(OracleModule.CSM)
    start_observability()

    web3 = build_oracle_web3(OracleWeb3Config(
        use_lido_contracts=False,
        use_csm_contracts=True,
        use_ipfs=True,
        use_performance_client=True,
    ))
    run_oracle_module(CSOracle(web3))
