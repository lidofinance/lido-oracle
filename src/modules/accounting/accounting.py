import logging
from functools import lru_cache

from src.modules.submodules.consensus import ConsensusModule, ZERO_HASH
from src.modules.submodules.oracle_module import BaseModule
from src.typings import BlockStamp
from src.web3py.typings import Web3

logger = logging.getLogger(__name__)


class Accounting(BaseModule, ConsensusModule):
    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    def __init__(self, w3: Web3):
        self.report_contract = w3.lido_contracts.accounting_oracle
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
            self.process_report(report_blockstamp)

        # Send third part data

    @lru_cache(maxsize=1)
    def build_report(self, blockstamp: BlockStamp) -> tuple:
        return (
            self.CONSENSUS_VERSION,
            blockstamp.slot_number,
            0,  # numValidators
            0,  # clBalanceGwei
            [],  # stakingModuleIdsWithNewlyExitedValidators
            [],  # numExitedValidatorsByStakingModule
            0,  # withdrawalVaultBalance
            0,  # elRewardsVaultBalance
            0,  # lastWithdrawalRequestIdToFinalize
            0,  # finalizationShareRate
            False,  # isBunkerMode
            1,  # extraDataFormat
            ZERO_HASH,  # extraDataHash
            0,  # extraDataItemsCount
        )

    @lru_cache(maxsize=1)
    def _get_processing_state(self, blockstamp: BlockStamp) -> tuple[int, int, bytes, bool, bytes, int, int, int]:
        """
        struct ProcessingState {
            uint256 currentFrameRefSlot;
            uint256 processingDeadlineTime;
            bytes32 mainDataHash;
            bool mainDataSubmitted;
            bytes32 extraDataHash;
            uint256 extraDataFormat;
            uint256 extraDataItemsCount;
            uint256 extraDataItemsSubmitted;
        }
        """
        return self.report_contract.functions.getProcessingState().call(block_identifier=blockstamp.block_hash)

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        return processing_state[3]

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        processing_state = self._get_processing_state(blockstamp)
        # --------- mainDataSubmitted ---- extraDataItemsCount -- extraDataItemsSubmitted --
        return not processing_state[3] or processing_state[6] != processing_state[7]
