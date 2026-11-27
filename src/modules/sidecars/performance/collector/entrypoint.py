from web3.eth import Eth

from src import variables
from src.modules.sidecars.performance.collector.collector import PerformanceCollector
from src.providers.consensus.client import ConsensusClient
from src.runtime import build_execution_provider, log_startup, start_observability
from src.types import OracleModuleName
from src.web3py.types import Web3


def _build_consensus_client() -> ConsensusClient:
    return ConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        variables.HTTP_REQUEST_TIMEOUT_CONSENSUS,
        variables.HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )


def _build_execution_client() -> Eth:
    return Web3(build_execution_provider()).eth


def run() -> None:
    log_startup(OracleModuleName.PERFORMANCE_COLLECTOR)
    start_observability()

    collector = PerformanceCollector(_build_consensus_client(), _build_execution_client())
    collector.run_as_daemon()
