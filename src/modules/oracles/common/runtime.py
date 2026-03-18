from collections.abc import Iterator
from typing import Any, TypeVar, cast

from packaging.version import Version
from web3_multi_provider.metrics import init_metrics

from src import constants, variables
from src.metrics.logging import logging
from src.metrics.prometheus.basic import init_basic_metrics
from src.modules.common.graceful_shutdown import graceful_shutdown_signal_handlers
from src.modules.oracles.common.oracle_module import OracleModule
from src.providers.ipfs import IPFSProvider, Kubo, LidoIPFS, Pinata, Storacha
from src.utils.exception import IncompatibleException
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    IPFS,
    ConsensusClientModule,
    FallbackProviderModule,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    TelemetryDataBus,
    TelemetryEventId,
    TransactionUtils,
)
from src.web3py.extensions.performance import PerformanceClientModule
from src.web3py.extensions.staking_module import StakingModuleContracts
from src.web3py.types import Web3, Web3Base, Web3StakingModule


logger = logging.getLogger(__name__)

W3 = TypeVar("W3", bound=Web3Base)


def _build_web3_base[W3: Web3Base](web3_cls: type[W3]) -> W3:
    logger.info({'msg': 'Initialize multi web3 provider.'})
    web3 = web3_cls(
        FallbackProviderModule(
            variables.EXECUTION_CLIENT_URI,
            request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
            cache_allowed_requests=True,
        )
    )

    logger.info({'msg': 'Modify web3 with custom contract function call.'})
    tweak_w3_contracts(web3)

    logger.info({'msg': 'Initialize consensus client.'})
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)

    logger.info({'msg': 'Initialize keys api client.'})
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)

    logger.info({'msg': 'Check configured providers.'})
    if Version(kac.get_status().appVersion) < constants.ALLOWED_KAPI_VERSION:
        raise IncompatibleException(f'Incompatible KAPI version. Required >= {constants.ALLOWED_KAPI_VERSION}.')

    check_providers_chain_ids(web3, cc, kac)

    modules: dict[str, Any] = {
        'transaction': TransactionUtils,
        'cc': lambda: cc,
        'kac': lambda: kac,
    }

    web3.attach_modules(modules)

    return web3


def build_oracle_web3(module_name: str) -> Web3:
    web3 = _build_web3_base(Web3)

    ipfs = IPFS(web3, ipfs_providers(), retries=variables.HTTP_REQUEST_RETRY_COUNT_IPFS)

    logger.info({'msg': 'Initialize DataBus telemetry module.'})
    telemetry_data_bus = TelemetryDataBus(
        variables.TELEMETRY_DATA_BUS_RPC,
        variables.DATA_BUS_ADDRESS,
        module_name,
        web3,
    )

    modules: dict[str, Any] = {
        'lido_contracts': LidoContracts,
        'lido_validators': LidoValidatorsProvider,
        'ipfs': lambda: ipfs,
        'telemetry_data_bus': lambda: telemetry_data_bus,
    }
    web3.attach_modules(modules)

    logger.info({'msg': 'Initialize prometheus metrics.'})
    init_metrics()
    init_basic_metrics(web3)

    return web3


def build_staking_module_web3(module_name: str) -> Web3StakingModule:
    web3 = _build_web3_base(Web3StakingModule)

    if not variables.PERFORMANCE_COLLECTOR_URI or '' in variables.PERFORMANCE_COLLECTOR_URI:
        raise ValueError("PERFORMANCE_COLLECTOR_URI is required")

    performance = PerformanceClientModule(variables.PERFORMANCE_COLLECTOR_URI)
    ipfs = IPFS(web3, ipfs_providers(), retries=variables.HTTP_REQUEST_RETRY_COUNT_IPFS)

    logger.info({'msg': 'Initialize DataBus telemetry module.'})
    telemetry_data_bus = TelemetryDataBus(
        variables.TELEMETRY_DATA_BUS_RPC,
        variables.DATA_BUS_ADDRESS,
        module_name,
        web3,
    )

    modules: dict[str, Any] = {
        'staking_module': StakingModuleContracts,
        'performance': lambda: performance,
        'ipfs': lambda: ipfs,
        'telemetry_data_bus': lambda: telemetry_data_bus,
    }
    web3.attach_modules(modules)

    logger.info({'msg': 'Initialize prometheus metrics.'})
    init_metrics()
    init_basic_metrics(web3)

    return web3


def run_oracle_module(module: OracleModule):
    module.check_contract_configs()

    try:
        module.w3.telemetry_data_bus.send_telemetry(TelemetryEventId.ORACLE_STARTUP)
    except Exception:
        logger.warning({'msg': 'Failed to send startup telemetry to DataBus.'}, exc_info=True)

    try:
        # Convert termination signals to SystemExit so regular cleanup in
        # `finally` still runs during process shutdown.
        with graceful_shutdown_signal_handlers():
            if variables.DAEMON:
                module.run_as_daemon()
            else:
                module.cycle_handler()
    finally:
        module.shutdown()


def check_providers_chain_ids(web3: Web3Base, cc: ConsensusClientModule, kac: KeysAPIClientModule):
    keys_api_chain_id = kac.check_providers_consistency()
    consensus_chain_id = cc.check_providers_consistency()
    execution_chain_id = cast(FallbackProviderModule, web3.provider).check_providers_consistency()

    if execution_chain_id == consensus_chain_id == keys_api_chain_id:
        return

    raise IncompatibleException(
        'Different chain ids detected:\n'
        f'Execution chain id: {execution_chain_id}\n'
        f'Consensus chain id: {consensus_chain_id}\n'
        f'Keys API chain id: {keys_api_chain_id}\n'
    )


def ipfs_providers() -> Iterator[IPFSProvider]:
    """
    Create IPFS providers in PRIORITY order.

    WARNING: Yields order here used for CID selection fallback when quorum
    consensus fails. Do not change order without considering impact.

    Storacha has highest priority because it's the only provider where we control
    the entire content addressing process. While other providers receive raw content
    and handle CAR/UnixFS assembly on their side (potentially with different
    implementations), Storacha receives our locally-assembled CAR files, ensuring
    the returned CID matches our own CAR conversion logic. This makes consensus
    more reliable when providers disagree on CID calculation.
    """
    if variables.STORACHA_AUTH_SECRET and variables.STORACHA_AUTHORIZATION and variables.STORACHA_SPACE_DID:
        yield Storacha(
            variables.STORACHA_AUTH_SECRET,
            variables.STORACHA_AUTHORIZATION,
            variables.STORACHA_SPACE_DID,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
        )

    if variables.LIDO_IPFS_HOST and variables.LIDO_IPFS_TOKEN:
        yield LidoIPFS(
            variables.LIDO_IPFS_HOST,
            variables.LIDO_IPFS_TOKEN,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
        )

    if variables.PINATA_JWT and variables.PINATA_DEDICATED_GATEWAY_URL and variables.PINATA_DEDICATED_GATEWAY_TOKEN:
        yield Pinata(
            variables.PINATA_JWT,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
            dedicated_gateway_url=variables.PINATA_DEDICATED_GATEWAY_URL,
            dedicated_gateway_token=variables.PINATA_DEDICATED_GATEWAY_TOKEN,
        )

    if variables.KUBO_HOST:
        yield Kubo(
            variables.KUBO_HOST,
            variables.KUBO_RPC_PORT,
            variables.KUBO_GATEWAY_PORT,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
        )
