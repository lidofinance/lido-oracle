import sys
from typing import Iterator, cast

from packaging.version import Version
from prometheus_client import start_http_server
from web3_multi_provider.metrics import init_metrics

from src import constants, variables
from src.constants import PRECISION_E27
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.metrics.prometheus.basic import BUILD_INFO, ENV_VARIABLES_INFO
from src.modules.accounting.accounting import Accounting
from src.modules.checks.checks_module import ChecksModule
from src.modules.csm.csm import CSOracle
from src.modules.ejector.ejector import Ejector
from src.providers.ipfs import IPFSProvider, Kubo, LidoIPFS, Pinata, Storacha
from src.types import OracleModule
from src.utils.build import get_build_info
from src.utils.exception import IncompatibleException
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    ConsensusClientModule,
    FallbackProviderModule,
    IPFS,
    KeysAPIClientModule,
    LazyCSM,
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
)
from src.web3py.types import Web3
from decimal import getcontext

getcontext().prec = PRECISION_E27

logger = logging.getLogger(__name__)


def main(module_name: OracleModule):
    build_info = get_build_info()
    logger.info({
        'msg': 'Oracle startup.',
        'variables': {
            **build_info,
            'module': module_name,
            **variables.PUBLIC_ENV_VARS,
        },
    })
    ENV_VARIABLES_INFO.info(variables.PUBLIC_ENV_VARS)
    BUILD_INFO.info(build_info)

    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)

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

    logger.info({'msg': 'Initialize IPFS providers.'})
    ipfs = IPFS(web3, ipfs_providers(), retries=variables.HTTP_REQUEST_RETRY_COUNT_IPFS)

    logger.info({'msg': 'Check configured providers.'})
    if Version(kac.get_status().appVersion) < constants.ALLOWED_KAPI_VERSION:
        raise IncompatibleException(f'Incompatible KAPI version. Required >= {constants.ALLOWED_KAPI_VERSION}.')

    check_providers_chain_ids(web3, cc, kac)

    web3.attach_modules({
        'lido_contracts': LidoContracts,
        'lido_validators': LidoValidatorsProvider,
        'transaction': TransactionUtils,
        'csm': LazyCSM,
        'cc': lambda: cc,  # type: ignore[dict-item]
        'kac': lambda: kac,  # type: ignore[dict-item]
        'ipfs': lambda: ipfs,  # type: ignore[dict-item]
    })

    logger.info({'msg': 'Initialize prometheus metrics.'})
    init_metrics()

    instance: Accounting | Ejector | CSOracle
    if module_name == OracleModule.ACCOUNTING:
        logger.info({'msg': 'Initialize Accounting module.'})
        instance = Accounting(web3)
    elif module_name == OracleModule.EJECTOR:
        logger.info({'msg': 'Initialize Ejector module.'})
        instance = Ejector(web3)
    elif module_name == OracleModule.CSM:
        logger.info({'msg': 'Initialize CSM performance oracle module.'})
        instance = CSOracle(web3)
    else:
        raise ValueError(f'Unexpected arg: {module_name=}.')

    instance.check_contract_configs()

    if variables.DAEMON:
        instance.run_as_daemon()
    else:
        instance.cycle_handler()


def check():
    logger.info({'msg': 'Check oracle is ready to work in the current environment.'})

    return ChecksModule().execute_module()


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



if __name__ == '__main__':
    module_name_arg = sys.argv[-1]
    if module_name_arg not in OracleModule:
        msg = f'Last arg should be one of {[str(item) for item in OracleModule]}, received {module_name_arg}.'
        logger.error({'msg': msg})
        raise ValueError(msg)

    module = OracleModule(module_name_arg)
    if module is OracleModule.CHECK:
        errors = variables.check_uri_required_variables()
        variables.raise_from_errors(errors)

        sys.exit(check())

    errors = variables.check_all_required_variables(module)
    variables.raise_from_errors(errors)
    main(module)
