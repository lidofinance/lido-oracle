import logging

from src.web3py.typings import Web3

from src.metrics.healthcheck_server import pulse


logger = logging.getLogger(__name__)


# ToDo fix wait for withdrawals function
def wait_for_withdrawals(w3: Web3):
    """Waits until protocol will be upgraded and be ready for new reports"""
    while True:
        logger.info({'msg': 'Check protocol ready for Oracle V3 reports.'})
        pulse()

        # lido_locator = w3.eth.contract(
        #     address=variables.LIDO_LOCATOR_ADDRESS,
        #     abi=LidoContracts.load_abi('LidoLocator'),
        # )

        return

        # ToDo check some kind of version somewhere
        # lido = w3.eth.contract(
        #     address=lido_locator.functions.accountingOracle().call(),
        #     abi=LidoContracts.load_abi('Lido'),
        # )
        # 0 is old Oracle Contract version
        # try:
        #     if lido.functions.getContractVersion().call() == 1:
        #         logger.info({'msg': 'Protocol is ready. Create Oracle instance.'})
        #         return
        # except:
        #     logger.info({'msg': 'Protocol is not ready for new oracle. Sleep for 1 epoch (384 seconds).'})
        #     time.sleep(32 * 12)
