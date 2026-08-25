from unittest.mock import Mock

import pytest

from src.modules.oracles.common.consensus import ConsensusModule
from src.types import BlockStamp, ReferenceBlockStamp


class SimpleConsensusModule(ConsensusModule):
    COMPATIBLE_CONTRACT_VERSION = 3
    COMPATIBLE_CONSENSUS_VERSION = 2

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
def consensus(web3):
    module = SimpleConsensusModule(web3)
    # _get_latest_data() fetches the current member list to feed the signer resolution
    # (w3.signer.process_members) on every call; give it a harmless default here so
    # tests that don't care about member resolution don't need to stub it individually.
    module._get_consensus_contract_members = Mock(return_value=([], []))
    return module
