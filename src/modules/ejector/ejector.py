from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import OracleModule
from src.typings import BlockStamp


class Ejector(OracleModule, ConsensusModule):
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

