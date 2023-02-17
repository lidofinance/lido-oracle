import pytest

from src.modules.submodules.consensus import ConsensusModule
from src.typings import BlockStamp, SlotNumber, BlockNumber, RefBlockStamp, EpochNumber


class SimpleConsensusModule(ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3):
        self.report_contract = w3.lido_contracts.accounting_oracle
        super().__init__(w3)

    def build_report(self, blockstamp: RefBlockStamp) -> tuple:
        return tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        return True

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return True


@pytest.fixture()
def consensus(web3, consensus_client, contracts):
    return SimpleConsensusModule(web3)


def get_blockstamp_by_state(w3, state_id) -> RefBlockStamp:
    root = w3.cc.get_block_root(state_id).root
    slot_details = w3.cc.get_block_details(root)

    return RefBlockStamp(
        ref_slot_number=SlotNumber(int(slot_details.message.slot)),
        ref_epoch=EpochNumber(SlotNumber(int(slot_details.message.slot)) // 32),
        block_root=root,
        slot_number=SlotNumber(int(slot_details.message.slot)),
        state_root=slot_details.message.state_root,
        block_number=BlockNumber(int(slot_details.message.body['execution_payload']['block_number'])),
        block_hash=slot_details.message.body['execution_payload']['block_hash']
    )
