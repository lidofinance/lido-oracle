from web3.eth import Eth

from src import variables
from src.modules.sidecars.performance.collector.collector import PerformanceCollector
from src.providers.consensus.client import ConsensusClient
from src.runtime import log_startup, start_observability
from src.types import OracleModuleName
from src.web3py.extensions import FallbackProviderModule
from src.web3py.types import Web3


def _build_consensus_client() -> ConsensusClient:
    return ConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        variables.HTTP_REQUEST_TIMEOUT_CONSENSUS,
        variables.HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )


def _build_execution_client() -> Eth:
    # Post-EIP-7732 a blockstamp's execution anchor is an EL block hash, and turning it into a block
    # number and timestamp needs an execution client. Only `eth` is used, no contracts.
    return Web3(
        FallbackProviderModule(
            variables.EXECUTION_CLIENT_URI,
            request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
            cache_allowed_requests=True,
        )
    ).eth


def run() -> None:
    log_startup(OracleModuleName.PERFORMANCE_COLLECTOR)
    start_observability()

    collector = PerformanceCollector(_build_consensus_client(), _build_execution_client())
    collector.run_as_daemon()
