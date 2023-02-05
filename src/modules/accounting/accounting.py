import logging

from src.modules.submodules.consensus import ConsensusModule
from src.blockchain.contracts import contracts
from src.modules.submodules.oracle_module import OracleModule
from src.typings import BlockStamp


logger = logging.getLogger(__name__)


class Accounting(OracleModule, ConsensusModule):
    def __init__(self, *args, **kwargs):
        self.report_contract = contracts.oracle
        super().__init__(*args, **kwargs)

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
