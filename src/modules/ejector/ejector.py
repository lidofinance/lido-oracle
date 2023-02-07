from web3.types import Wei

from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp, Web3


class Ejector(BaseModule, ConsensusModule):
    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.validator_exit_bus
        super().__init__(w3)

    def execute_module(self, blockstamp: BlockStamp):
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.build_report(report_blockstamp)

    def build_report(self, blockstamp: BlockStamp):
        """
        1. Get total eth to withdraw
        2. Get total current eth
        3. Get total predicted eth
        4. Get total eth to ejecte
        5. Ejection module.
        """
        pass

    def _get_amount_wei_to_withdraw(self) -> Wei:
        # x - val_to_eject
        # to_eject = curr_eth + x * 32 + predicted_eth(line_to_withdraw_in_epoch) + predicted_eth(x/eject_in_epoch)
        pass

    # Code from prev version of Oracle
    # def get_withdrawal_requests_wei_amount(block_hash: HexBytes) -> int:
    #     total_pooled_ether = contracts.lido.functions.getTotalPooledEther().call(block_identifier=block_hash)
    #     logger.info({'msg': 'Get total pooled ether.', 'value': total_pooled_ether})
    #
    #     total_shares = contracts.lido.functions.getSharesByPooledEth(total_pooled_ether).call(block_identifier=block_hash)
    #     logger.info({'msg': 'Get total shares.', 'value': total_shares})
    #
    #     queue_length = contracts.withdrawal_queue.functions.queueLength().call(block_identifier=block_hash)
    #     logger.info({'msg': 'Get last id to finalize.', 'value': total_pooled_ether})
    #
    #     if queue_length == 0:
    #         logger.info({'msg': 'Withdrawal queue is empty.'})
    #         return 0
    #
    #     return contracts.withdrawal_queue.functions.calculateFinalizationParams(
    #         queue_length - 1,
    #         total_pooled_ether,
    #         total_shares,
    #     ).call(block_identifier=block_hash)
