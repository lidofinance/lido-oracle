import variables
from modules.sidecars.performance.collector.collector import PerformanceCollector
from providers.consensus.client import ConsensusClient
from runtime import log_startup, start_observability
from type_aliases import OracleModuleName


def _build_consensus_client() -> ConsensusClient:
    return ConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        variables.HTTP_REQUEST_TIMEOUT_CONSENSUS,
        variables.HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )


def run() -> None:
    log_startup(OracleModuleName.PERFORMANCE_COLLECTOR)
    start_observability()

    collector = PerformanceCollector(_build_consensus_client())
    collector.run_as_daemon()
