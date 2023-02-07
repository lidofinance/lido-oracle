import logging

from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp
from src.web3_extentions.typings import Web3

logger = logging.getLogger(__name__)


class Accounting(BaseModule, ConsensusModule):
    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.oracle
        super().__init__(w3)

    def execute_module(self, blockstamp: BlockStamp):
        """
        1. Get slot to report getMemberInfo(address)
        2. If slot finalized - build report for slot
        3. Check members hash
            1. If it is actual - no steps
            2. If this is old hash - resubmit to new
        4. If consensus are done - send report data
        5. Send extra data
        """
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.build_report(report_blockstamp)

    def build_report(self, blockstamp: BlockStamp):
        pass
