import sys

from prometheus_client import start_http_server
from web3 import Web3
from web3_multi_provider import MultiProvider

from src import variables
from src.blockchain import contracts
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.modules.accounting import Accounting
from src.protocol_upgrade_checker import wait_for_withdrawals
from src.providers.consensus.client import ConsensusClient
from src.metrics.web3 import add_requests_metric_middleware
from src.typings import Module

logger = logging.getLogger()


if __name__ == '__main__':
    module_name = sys.argv[-1]
    if module_name not in Module._value2member_map_:
        msg = f'Last arg should be one of {list(Module._value2member_map_.keys())}, received {module_name}.'
        logger.error({'msg': msg})
        raise ValueError(msg)

    logger.info({
        'msg': 'Oracle startup.',
        'variables': {
            'module': module_name,
            'ACCOUNT': variables.ACCOUNT.address if variables.ACCOUNT else 'Dry',
            'LIDO_CONTRACT_ADDRESS': variables.LIDO_CONTRACT_ADDRESS,
            'GAS_LIMIT': variables.GAS_LIMIT,
            'MAX_CYCLE_LIFETIME_IN_SECONDS': variables.MAX_CYCLE_LIFETIME_IN_SECONDS,
        },
    })

    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)

    logger.info({'msg': 'Initialize multi web3 provider.'})
    w3 = Web3(MultiProvider(variables.EXECUTION_CLIENT_URI))

    logger.info({'msg': 'Add metrics middleware for ETH1 requests.'})
    add_requests_metric_middleware(w3)

    logger.info({'msg': 'Check protocol version.'})
    wait_for_withdrawals(w3)

    logger.info({'msg': 'Initialize contracts.'})
    contracts.initialize(w3)

    logger.info({'msg': 'Initialize Consensus Layer client.'})
    cc = ConsensusClient(variables.CONSENSUS_CLIENT_URI)

    if module_name == Module.ACCOUNTING:
        logger.info({'msg': 'Initialize Accounting module.'})
        accounting = Accounting(w3, cc)
        accounting.run_as_daemon()
    elif module_name == Module.EJECTOR:
        pass
