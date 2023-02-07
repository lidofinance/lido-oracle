from web3.types import Wei

from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp


class Ejector(BaseModule, ConsensusModule):
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
