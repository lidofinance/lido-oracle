import logging
import time

from web3 import Web3

from src import variables


logger = logging.getLogger(__name__)


def wait_for_withdrawals(w3: Web3):
    """Waits until protocol will be upgraded and be ready for new reports"""
    lido = w3.eth.contract(
        address=variables.LIDO_CONTRACT_ADDRESS,
    )

    while True:
        logger.info({'msg': 'Check protocol ready for Oracle V3 reports.'})

        oracle = lido.functions.getOracle().call()
        logger.info({'msg': 'Call getOracle function.', 'value': oracle})

        if oracle != '0x442af784A788A5bd6F42A01Ebe9F287a871243fb':
            logger.info({'msg': 'Protocol is ready. Create Oracle instance.'})
            return
        else:
            logger.info({'msg': 'Protocol is not ready. Sleep for 384 seconds.'})
            time.sleep(32*12)
