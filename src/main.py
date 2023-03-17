import sys
from typing import cast

from prometheus_client import start_http_server
from web3_multi_provider import MultiProvider  # type: ignore[import]
from web3.middleware import simple_cache_middleware

from src import variables
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.metrics.prometheus.basic import ENV_VARIABLES_INFO, BUILD_INFO
from src.modules.accounting.accounting import Accounting
from src.modules.ejector.ejector import Ejector
from src.typings import OracleModule
from src.utils.build import get_build_info
from src.web3py.extensions import (
    LidoContracts,
    TransactionUtils,
    ConsensusClientModule,
    KeysAPIClientModule,
    LidoValidatorsProvider,
)
from src.web3py.middleware import metrics_collector
from src.web3py.typings import Web3

from src.web3py.contract_tweak import tweak_w3_contracts


logger = logging.getLogger()


def main(module_name: OracleModule):
    build_info = get_build_info()
    logger.info({
        'msg': 'Oracle startup.',
        'variables': {
            **build_info,
            'module': module_name,
            'ACCOUNT': variables.ACCOUNT.address if variables.ACCOUNT else 'Dry',
            'LIDO_LOCATOR_ADDRESS': variables.LIDO_LOCATOR_ADDRESS,
            'MAX_CYCLE_LIFETIME_IN_SECONDS': variables.MAX_CYCLE_LIFETIME_IN_SECONDS,
        },
    })
    ENV_VARIABLES_INFO.info({
        "ACCOUNT": str(variables.ACCOUNT.address) if variables.ACCOUNT else 'Dry',
        "LIDO_LOCATOR_ADDRESS": str(variables.LIDO_LOCATOR_ADDRESS),
        "FINALIZATION_BATCH_MAX_REQUEST_COUNT": str(variables.FINALIZATION_BATCH_MAX_REQUEST_COUNT),
        "MAX_CYCLE_LIFETIME_IN_SECONDS": str(variables.MAX_CYCLE_LIFETIME_IN_SECONDS),
    })
    BUILD_INFO.info(build_info)

    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)

    logger.info({'msg': 'Initialize multi web3 provider.'})
    web3 = Web3(MultiProvider(variables.EXECUTION_CLIENT_URI))

    logger.info({'msg': 'Modify web3 with custom contract function call.'})
    tweak_w3_contracts(web3)

    logger.info({'msg': 'Initialize consensus client.'})
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)

    logger.info({'msg': 'Initialize keys api client.'})
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)

    web3.attach_modules({
        'lido_contracts': LidoContracts,
        'lido_validators': LidoValidatorsProvider,
        'transaction': TransactionUtils,
        'cc': lambda: cc,  # type: ignore[dict-item]
        'kac': lambda: kac,  # type: ignore[dict-item]
    })

    logger.info({'msg': 'Add metrics middleware for ETH1 requests.'})
    web3.middleware_onion.add(metrics_collector)
    web3.middleware_onion.add(simple_cache_middleware)

    logger.info({'msg': 'Sanity checks.'})
    check_providers_chain_ids(web3)

    if module_name == OracleModule.ACCOUNTING:
        logger.info({'msg': 'Initialize Accounting module.'})
        accounting = Accounting(web3)
        accounting.check_contract_configs()
        accounting.run_as_daemon()
    elif module_name == OracleModule.EJECTOR:
        logger.info({'msg': 'Initialize Ejector module.'})
        ejector = Ejector(web3)
        ejector.check_contract_configs()
        ejector.run_as_daemon()


def check_required_variables():
    errors = []
    if '' in variables.EXECUTION_CLIENT_URI:
        errors.append('EXECUTION_CLIENT_URI')
    if variables.CONSENSUS_CLIENT_URI == '':
        errors.append('CONSENSUS_CLIENT_URI')
    if variables.KEYS_API_URI == '':
        errors.append('KEYS_API_URI')
    if variables.LIDO_LOCATOR_ADDRESS in (None, ''):
        errors.append('LIDO_LOCATOR_ADDRESS')
    if errors:
        raise ValueError("The following variables are required: " + ", ".join(errors))


def check_providers_chain_ids(web3: Web3):
    execution_chain_id = web3.eth.chain_id
    consensus_chain_id = int(web3.cc.get_config_spec().DEPOSIT_CHAIN_ID)
    chain_ids = [Web3.to_int(hexstr=provider.make_request("eth_chainId", []).get('result'))
                 for provider in cast(MultiProvider, web3.provider)._providers]  # type: ignore[attr-defined] # pylint: disable=protected-access
    keys_api_chain_id = web3.kac.get_status().chainId
    if any(execution_chain_id != chain_id for chain_id in [*chain_ids, consensus_chain_id, keys_api_chain_id]):
        raise ValueError('Different chain ids detected:\n'
                         f'Execution chain ids: {", ".join(map(str, chain_ids))}\n'
                         f'Consensus chain id: {consensus_chain_id}\n'
                         f'Keys API chain id: {keys_api_chain_id}\n')


if __name__ == '__main__':
    last_arg = sys.argv[-1]
    if last_arg not in iter(OracleModule):
        msg = f'Last arg should be one of {[str(item) for item in OracleModule]}, received {last_arg}.'
        logger.error({'msg': msg})
        raise ValueError(msg)

    check_required_variables()
    main(OracleModule(last_arg))
