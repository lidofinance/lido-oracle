from functools import lru_cache

from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp, RefBlockStamp
from src.web3py.typings import Web3


class Ejector(BaseModule, ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.validators_exit_bus_oracle
        super().__init__(w3)

    def execute_module(self, blockstamp: RefBlockStamp):
        report_blockstamp = self.get_blockstamp_for_report(blockstamp)
        if report_blockstamp:
            self.process_report(report_blockstamp)

    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: RefBlockStamp) -> tuple:
        return (
            self.CONSENSUS_VERSION,
            blockstamp.slot_number,
            0,
            0,
            b'',
        )

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> tuple[int, int, bytes, bool, int, int, int]:
        """
        struct ProcessingState {
            uint256 currentFrameRefSlot;
            uint256 processingDeadlineTime;
            bytes32 dataHash;
            bool dataSubmitted;
            uint256 dataFormat;
            uint256 requestsCount;
            uint256 requestsSubmitted;
        }
        """
        return self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash)

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state[3]

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        # --------- mainDataSubmitted ---- requestsCount ------- requestsSubmitted --
        return not processing_state[3] or processing_state[5] != processing_state[6]
