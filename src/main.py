import sys

from prometheus_client import start_http_server
from web3_multi_provider import MultiProvider

from src import variables
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.modules.accounting.accounting import Accounting
from src.modules.ejector.ejector import Ejector
from src.protocol_upgrade_checker import wait_for_withdrawals
from src.typings import OracleModule, Web3
from src.web3_extentions import (
    LidoContracts,
    TransactionUtils,
    ConsensusClientModule,
    KeysAPIClientModule,
    metrics_collector,
)


logger = logging.getLogger()


if __name__ == '__main__':
    module_name = sys.argv[-1]
    if module_name not in OracleModule._value2member_map_:
        msg = f'Last arg should be one of {list(OracleModule._value2member_map_.keys())}, received {module_name}.'
        logger.error({'msg': msg})
        raise ValueError(msg)

    logger.info({
        'msg': 'Oracle startup.',
        'variables': {
            'module': module_name,
            'ACCOUNT': variables.ACCOUNT.address if variables.ACCOUNT else 'Dry',
            'LIDO_LOCATOR_ADDRESS': variables.LIDO_LOCATOR_ADDRESS,
            'GAS_LIMIT': variables.GAS_LIMIT,
            'MAX_CYCLE_LIFETIME_IN_SECONDS': variables.MAX_CYCLE_LIFETIME_IN_SECONDS,
        },
    })

    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)

    logger.info({'msg': 'Initialize multi web3 provider.'})
    web3 = Web3(MultiProvider(variables.EXECUTION_CLIENT_URI))

    web3.attach_modules({
        'lido_contracts': LidoContracts,
        'transaction': TransactionUtils,
        'cc': lambda: ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3),
        'kac': lambda: KeysAPIClientModule(variables.KEYS_API_URI, web3),
    })

    logger.info({'msg': 'Add metrics middleware for ETH1 requests.'})
    web3.middleware_onion.add(metrics_collector)

    logger.info({'msg': 'Check protocol version.'})
    wait_for_withdrawals(web3)

    if module_name == OracleModule.ACCOUNTING:
        logger.info({'msg': 'Initialize Accounting module.'})
        accounting = Accounting(web3)
        accounting.run_as_daemon()
    elif module_name == OracleModule.EJECTOR:
        logger.info({'msg': 'Initialize Ejector module.'})
        ejector = Ejector(web3)
        ejector.run_as_daemon()
