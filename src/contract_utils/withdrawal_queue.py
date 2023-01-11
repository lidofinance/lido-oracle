import logging

from hexbytes import HexBytes

from src.contracts import contracts


logger = logging.getLogger(__name__)


def get_withdrawal_requests_wei_amount(block_hash: HexBytes) -> int:
    total_pooled_ether = contracts.lido.functions.getTotalPooledEther().call(block_identifier=block_hash)
    logger.info({'msg': 'Get total pooled ether.', 'value': total_pooled_ether})

    total_shares = contracts.lido.functions.getSharesByPooledEth(total_pooled_ether).call(block_identifier=block_hash)
    logger.info({'msg': 'Get total shares.', 'value': total_shares})

    queue_length = contracts.withdrawal_queue.functions.queueLength().call(block_identifier=block_hash)
    logger.info({'msg': 'Get last id to finalize.', 'value': total_pooled_ether})

    if queue_length == 0:
        logger.info({'msg': 'Withdrawal queue is empty.'})
        return 0

    return contracts.withdrawal_queue.functions.calculateFinalizationParams(
        queue_length - 1,
        total_pooled_ether,
        total_shares,
    ).call(block_identifier=block_hash)
