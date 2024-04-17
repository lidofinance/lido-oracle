import pytest

from src.modules.submodules.consensus import ConsensusModule
from src.types import BlockStamp, ReferenceBlockStamp


class SimpleConsensusModule(ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        return tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        return True

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return True

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        return True


@pytest.fixture()
def consensus(web3, consensus_client, contracts):
    return SimpleConsensusModule(web3)
