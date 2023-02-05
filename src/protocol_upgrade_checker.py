import logging
import time

from web3 import Web3

from src import variables
from src.blockchain import contracts
from src.metrics.healthcheck_server import pulse


logger = logging.getLogger(__name__)


def wait_for_withdrawals(w3: Web3):
    """Waits until protocol will be upgraded and be ready for new reports"""
    while True:
        logger.info({'msg': 'Check protocol ready for Oracle V3 reports.'})
        pulse()

        lido = w3.eth.contract(
            address=variables.LIDO_CONTRACT_ADDRESS,
            abi=contracts.load_abi('Lido'),
        )

        oracle_address = lido.functions.getOracle().call()

        oracle = w3.eth.contract(
            address=oracle_address,
            abi=contracts.load_abi('LidoOracle')
        )

        # 0 is old Oracle Contract version
        if oracle.functions.getVersion().call() != 0:
            logger.info({'msg': 'Protocol is ready. Create Oracle instance.'})
            return
        else:
            logger.info({'msg': 'Protocol is not ready for new oracle. Sleep for 1 epoch (384 seconds).'})
            time.sleep(32 * 12)
