from dataclasses import dataclass
from typing import Iterator, cast, Any

from packaging.version import Version
from web3_multi_provider.metrics import init_metrics

from src import constants, variables
from src.metrics.logging import logging
from src.modules.oracles.common.types import OracleModule
from src.providers.ipfs import IPFSProvider, Kubo, LidoIPFS, Pinata, Storacha
from src.utils.exception import IncompatibleException
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    ConsensusClientModule,
    FallbackProviderModule,
    IPFS,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)
from src.web3py.extensions.staking_module import StakingModuleContracts
from src.web3py.extensions.performance import PerformanceClientModule
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OracleWeb3Config:
    use_ipfs: bool = False
    use_performance_client: bool = False
    use_staking_module_contracts: bool = False
    use_lido_contracts: bool = True
    use_lido_validators: bool = True


def build_oracle_web3(config: OracleWeb3Config) -> Web3:
    logger.info({'msg': 'Initialize multi web3 provider.'})
    web3 = Web3(FallbackProviderModule(
        variables.EXECUTION_CLIENT_URI,
        request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
        cache_allowed_requests=True,
    ))

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

    if config.use_lido_contracts:
        modules['lido_contracts'] = LidoContracts

    if config.use_lido_validators:
        modules['lido_validators'] = LidoValidatorsProvider

    if config.use_staking_module_contracts:
        modules['staking_module'] = StakingModuleContracts

    if config.use_ipfs:
        ipfs = IPFS(web3, ipfs_providers(), retries=variables.HTTP_REQUEST_RETRY_COUNT_IPFS)
        modules['ipfs'] = lambda: ipfs

    if config.use_performance_client:
        performance = PerformanceClientModule(variables.PERFORMANCE_COLLECTOR_URI)
        modules['performance'] = lambda: performance

    web3.attach_modules(modules)

    logger.info({'msg': 'Initialize prometheus metrics.'})
    init_metrics()

    return web3


def run_oracle_module(module: OracleModule):
    module.check_contract_configs()

    if variables.DAEMON:
        module.run_as_daemon()
    else:
        module.cycle_handler()


def check_providers_chain_ids(web3: Web3, cc: ConsensusClientModule, kac: KeysAPIClientModule):
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
    if variables.KUBO_HOST:
        yield Kubo(
            variables.KUBO_HOST,
            variables.KUBO_RPC_PORT,
            variables.KUBO_GATEWAY_PORT,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
        )

    if variables.PINATA_JWT and variables.PINATA_DEDICATED_GATEWAY_URL and variables.PINATA_DEDICATED_GATEWAY_TOKEN:
        yield Pinata(
            variables.PINATA_JWT,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
            dedicated_gateway_url=variables.PINATA_DEDICATED_GATEWAY_URL,
            dedicated_gateway_token=variables.PINATA_DEDICATED_GATEWAY_TOKEN,
        )

    if (
        variables.STORACHA_AUTH_SECRET and
        variables.STORACHA_AUTHORIZATION and
        variables.STORACHA_SPACE_DID
    ):
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
