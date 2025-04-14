import argparse
import sys
from typing import Iterator, cast

from packaging.version import Version
from prometheus_client import start_http_server

from src import constants
from src import variables
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.metrics.prometheus.basic import ENV_VARIABLES_INFO, BUILD_INFO
from src.modules.accounting.accounting import Accounting
from src.modules.checks.checks_module import execute_checks
from src.modules.csm.csm import CSOracle
from src.modules.ejector.ejector import Ejector
from src.providers.ipfs import GW3, IPFSProvider, MultiIPFSProvider, Pinata, PublicIPFS
from src.types import OracleModule, BlockRoot, SlotNumber
from src.utils.blockstamp import build_blockstamp
from src.utils.build import get_build_info
from src.utils.exception import IncompatibleException
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    LidoContracts,
    TransactionUtils,
    ConsensusClientModule,
    KeysAPIClientModule,
    LidoValidatorsProvider,
    FallbackProviderModule,
    LazyCSM,
)
from src.web3py.middleware import add_requests_metric_middleware
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


def _construct_web3() -> Web3:
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
    ipfs = MultiIPFSProvider(
        ipfs_providers(),
        retries=variables.HTTP_REQUEST_RETRY_COUNT_IPFS,
    )

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

    logger.info({'msg': 'Add metrics middleware for ETH1 requests.'})
    add_requests_metric_middleware(web3)
    return web3


def _construct_module(web3: Web3, module_name: OracleModule) -> Accounting | Ejector | CSOracle:
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

    logger.info({'msg': 'Sanity checks.'})
    instance.check_contract_configs()
    return instance


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
    web3 = _construct_web3()
    instance: Accounting | Ejector | CSOracle = _construct_module(web3, module_name)
    if variables.DAEMON:
        instance.run_as_daemon()
    else:
        instance.cycle_handler()


def run_on_refslot(module_name: OracleModule, slot: int):
    w3 = _construct_web3()
    instance: Accounting | Ejector | CSOracle = _construct_module(w3, module_name)
    instance.check_contract_configs()

    block_root = BlockRoot(w3.cc.get_block_root(SlotNumber(slot + 3 * 32)).root)
    block_details = w3.cc.get_block_details(block_root)
    bs = build_blockstamp(block_details)

    instance.refresh_contracts_and_run_cycle(bs)


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
    if variables.GW3_ACCESS_KEY and variables.GW3_SECRET_KEY:
        yield GW3(
            variables.GW3_ACCESS_KEY,
            variables.GW3_SECRET_KEY,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
        )

    if variables.PINATA_JWT:
        yield Pinata(
            variables.PINATA_JWT,
            timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS,
        )

    yield PublicIPFS(timeout=variables.HTTP_REQUEST_TIMEOUT_IPFS)


def parse_args():
    """
    Parse command-line arguments using argparse.
    The 'module' argument is restricted to valid OracleModule values.
    """
    valid_modules = [str(item) for item in OracleModule]

    parser = argparse.ArgumentParser(description="Run the Oracle module process.")
    subparsers = parser.add_subparsers(dest="module", required=True, help=f"Module to run. One of: {valid_modules}")
    check_parser = subparsers.add_parser("check", help="Run the check module.")
    check_parser.add_argument(
        "--name",
        "-n",
        type=str,
        default=None,
        help="Module name to check for a refslot execution."
    )
    check_parser.add_argument(
        "--refslot",
        "-r",
        type=str,
        default=None,
        help="Refslot parameter for the check module. If it is set it will run oracle on a specific refslot."
    )
    for mod in OracleModule:
        if mod == OracleModule.CSM:
            continue
        subparsers.add_parser(mod.value(), help=f"Run the {mod.value()} module.")

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    if args.module not in OracleModule:
        msg = f'Last arg should be one of {[str(item) for item in OracleModule]}, received {args.module}.'
        logger.error({'msg': msg})
        raise ValueError(msg)

    module = OracleModule(args.module)
    if module is OracleModule.CHECK:
        if args.refslot is None and args.name is None:
            errors = variables.check_uri_required_variables()
            variables.raise_from_errors(errors)
            sys.exit(execute_checks())
        else:
            errors = variables.check_all_required_variables(module)
            variables.raise_from_errors(errors)
            run_on_refslot(args.name, args.refslot)
            sys.exit(0)

    errors = variables.check_all_required_variables(module)
    variables.raise_from_errors(errors)
    main(module)
