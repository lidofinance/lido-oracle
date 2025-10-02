import logging

from hexbytes import HexBytes

from src.constants import UINT64_MAX
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.csm import (
    CSM_CURRENT_FRAME_RANGE_L_EPOCH,
    CSM_CURRENT_FRAME_RANGE_R_EPOCH,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.csm.checkpoint import (
    FrameCheckpointProcessor,
    FrameCheckpointsIterator,
    MinStepIsNotReached,
)
from src.modules.csm.distribution import (
    Distribution,
    DistributionResult,
    StrikesValidator,
)
from src.modules.csm.helpers.last_report import LastReport
from src.modules.csm.log import FramePerfLog
from src.modules.csm.state import State
from src.modules.csm.tree import RewardsTree, StrikesTree, Tree
from src.modules.csm.types import ReportData, RewardsShares, StrikesList
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.types import ZERO_HASH
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.exceptions import InconsistentData
from src.providers.ipfs import CID
from src.types import (
    BlockStamp,
    EpochNumber,
    ReferenceBlockStamp,
    SlotNumber,
)
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import NodeOperatorId
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class CSMError(Exception):
    """Unrecoverable error in CSM module"""


class CSOracle(BaseModule, ConsensusModule):
    """
    CSM performance module collects performance of CSM node operators and creates a Merkle tree of the resulting
    distribution of shares among the operators. The root of the tree is then submitted to the module contract.

    The algorithm for calculating performance includes the following steps:
        1. Collect all the attestation duties of the network validators for the frame.
        2. Calculate the performance of each validator based on the attestations.
        3. Calculate the share of each CSM node operator excluding underperforming validators.
    """

    COMPATIBLE_CONTRACT_VERSION = 2
    COMPATIBLE_CONSENSUS_VERSION = 3

    report_contract: CSFeeOracleContract

    def __init__(self, w3: Web3):
        self.report_contract = w3.csm.oracle
        self.state = State.load()
        super().__init__(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.csm.oracle  # type: ignore
        self.state.clear()

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        if not self._check_compatability(last_finalized_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        collected = self.collect_data(last_finalized_blockstamp)
        if not collected:
            logger.info(
                {"msg": "Data required for the report is not fully collected yet. Waiting for the next finalized epoch"}
            )
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)
        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        self.validate_state(blockstamp)

        last_report = self._get_last_report(blockstamp)
        rewards_tree_root, rewards_cid = last_report.rewards_tree_root, last_report.rewards_tree_cid

        distribution = self.calculate_distribution(blockstamp, last_report)

        if distribution.total_rewards:
            rewards_tree = self.make_rewards_tree(distribution.total_rewards_map)
            rewards_tree_root = rewards_tree.root
            rewards_cid = self.publish_tree(rewards_tree)

        if distribution.strikes:
            strikes_tree = self.make_strikes_tree(distribution.strikes)
            strikes_tree_root = strikes_tree.root
            strikes_cid = self.publish_tree(strikes_tree)
            if strikes_tree_root == last_report.strikes_tree_root:
                logger.info({"msg": "Strikes tree is the same as the previous one"})
            if (strikes_cid == last_report.strikes_tree_cid) != (strikes_tree_root == last_report.strikes_tree_root):
                raise ValueError(f"Invalid strikes tree built: {strikes_cid=}, {strikes_tree_root=}")
        else:
            strikes_tree_root = HexBytes(ZERO_HASH)
            strikes_cid = None

        logs_cid = self.publish_log(distribution.logs)

        return ReportData(
            consensus_version=self.get_consensus_version(blockstamp),
            ref_slot=blockstamp.ref_slot,
            tree_root=rewards_tree_root,
            tree_cid=rewards_cid or "",
            log_cid=logs_cid,
            distributed=distribution.total_rewards,
            rebate=distribution.total_rebate,
            strikes_tree_root=strikes_tree_root,
            strikes_tree_cid=strikes_cid or "",
        ).as_tuple()

    def _get_last_report(self, blockstamp: ReferenceBlockStamp) -> LastReport:
        current_frame = self.get_frame_number_by_slot(blockstamp)
        return LastReport.load(self.w3, blockstamp, current_frame)

    def calculate_distribution(self, blockstamp: ReferenceBlockStamp, last_report: LastReport) -> DistributionResult:
        distribution = Distribution(self.w3, self.converter(blockstamp), self.state)
        result = distribution.calculate(blockstamp, last_report)
        return result

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        last_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        ref_slot = self.get_initial_or_current_frame(blockstamp).ref_slot
        return last_ref_slot == ref_slot

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self.report_contract.is_paused('latest')
        CONTRACT_ON_PAUSE.labels("csm").set(on_pause)
        return not on_pause

    def validate_state(self, blockstamp: ReferenceBlockStamp) -> None:
        # NOTE: We cannot use `r_epoch` from the `current_frame_range` call because the `blockstamp` is a
        # `ReferenceBlockStamp`, hence it's a block the frame ends at. We use `ref_epoch` instead.
        l_epoch, _ = self.get_epochs_range_to_process(blockstamp)
        r_epoch = blockstamp.ref_epoch

        self.state.validate(l_epoch, r_epoch)

    def collect_data(self, blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection for the estimated reference slot"""

        logger.info({"msg": "Collecting data for the report"})

        converter = self.converter(blockstamp)

        l_epoch, r_epoch = self.get_epochs_range_to_process(blockstamp)
        logger.info({"msg": f"Epochs range for performance data collect: [{l_epoch};{r_epoch}]"})

        # NOTE: Finalized slot is the first slot of justifying epoch, so we need to take the previous. But if the first
        # slot of the justifying epoch is empty, blockstamp.slot_number will point to the slot where the last finalized
        # block was created. As a result, finalized_epoch in this case will be less than the actual number of the last
        # finalized epoch. As a result we can have a delay in frame finalization.
        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(blockstamp.slot_number) - 1)

        report_blockstamp = self.get_blockstamp_for_report(blockstamp)

        if not report_blockstamp:
            logger.info({"msg": "No report blockstamp available, using pre-computed one for collecting data"})

        if report_blockstamp and report_blockstamp.ref_epoch != r_epoch:
            logger.warning(
                {
                    "msg": f"Epochs range has been changed, but the change is not yet observed on finalized epoch {finalized_epoch}"
                }
            )
            return False

        if l_epoch > finalized_epoch:
            logger.info({"msg": "The starting epoch of the epochs range is not finalized yet"})
            return False

        self.state.migrate(l_epoch, r_epoch, converter.frame_config.epochs_per_frame)
        self.state.log_progress()

        if self.state.is_fulfilled:
            logger.info({"msg": "All epochs are already processed. Nothing to collect"})
            return True

        try:
            checkpoints = FrameCheckpointsIterator(
                converter,
                min(self.state.unprocessed_epochs),
                r_epoch,
                finalized_epoch,
            )
        except MinStepIsNotReached:
            return False

        processor = FrameCheckpointProcessor(self.w3.cc, self.state, converter, blockstamp)

        for checkpoint in checkpoints:
            if self.get_epochs_range_to_process(self._receive_last_finalized_slot()) != (l_epoch, r_epoch):
                logger.info({"msg": "Checkpoints were prepared for an outdated epochs range, stop processing"})
                raise ValueError("Outdated checkpoint")
            processor.exec(checkpoint)
            # Reset BaseOracle cycle timeout to avoid timeout errors during long checkpoints processing
            self._reset_cycle_timeout()
        return self.state.is_fulfilled

    def make_rewards_tree(self, shares: dict[NodeOperatorId, RewardsShares]) -> RewardsTree:
        if not shares:
            raise ValueError("No shares to build a tree")

        # XXX: We put a stone here to make sure, that even with only 1 node operator in the tree, it's still possible to
        # claim rewards. The CSModule contract skips pulling rewards if the proof's length is zero, which is the case
        # when the tree has only one leaf.
        stone = NodeOperatorId(self.w3.csm.module.MAX_OPERATORS_COUNT)
        shares[stone] = 0

        # XXX: Remove the stone as soon as we have enough leafs to build a suitable tree.
        if stone in shares and len(shares) > 2:
            shares.pop(stone)

        tree = RewardsTree.new(tuple(shares.items()))
        logger.info({"msg": "New rewards tree built for the report", "root": repr(tree.root)})
        return tree

    def make_strikes_tree(self, strikes: dict[StrikesValidator, StrikesList]) -> StrikesTree:
        if not strikes:
            raise ValueError("No strikes to build a tree")
        tree = StrikesTree.new(tuple((no_id, pubkey, strikes) for ((no_id, pubkey), strikes) in strikes.items()))
        logger.info({"msg": "New strikes tree built for the report", "root": repr(tree.root)})
        return tree

    def publish_tree(self, tree: Tree) -> CID:
        tree_cid = self.w3.ipfs.publish(tree.encode())
        logger.info({"msg": "Tree dump uploaded to IPFS", "cid": repr(tree_cid)})
        return tree_cid

    def publish_log(self, logs: list[FramePerfLog]) -> CID:
        log_cid = self.w3.ipfs.publish(FramePerfLog.encode(logs))
        logger.info({"msg": "Frame(s) log uploaded to IPFS", "cid": repr(log_cid)})
        return log_cid

    @lru_cache(maxsize=1)
    def get_epochs_range_to_process(self, blockstamp: BlockStamp) -> tuple[EpochNumber, EpochNumber]:
        converter = self.converter(blockstamp)

        far_future_initial_epoch = converter.get_epoch_by_timestamp(UINT64_MAX)
        if converter.frame_config.initial_epoch == far_future_initial_epoch:
            raise ValueError("CSM oracle initial epoch is not set yet")

        l_ref_slot = last_processing_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        r_ref_slot = initial_ref_slot = self.get_initial_ref_slot(blockstamp)

        if last_processing_ref_slot > blockstamp.slot_number:
            raise InconsistentData(f"{last_processing_ref_slot=} > {blockstamp.slot_number=}")

        # The very first report, no previous ref slot.
        if not last_processing_ref_slot:
            l_ref_slot = SlotNumber(initial_ref_slot - converter.slots_per_frame)
            if l_ref_slot < 0:
                raise CSMError("Invalid frame configuration for the current network")

        # NOTE: before the initial slot the contract can't return current frame
        if blockstamp.slot_number > initial_ref_slot:
            r_ref_slot = self.get_initial_or_current_frame(blockstamp).ref_slot

        # We are between reports, next report slot didn't happen yet. Predicting the next ref slot for the report
        # to calculate epochs range to collect the data.
        if l_ref_slot == r_ref_slot:
            r_ref_slot = converter.get_epoch_last_slot(
                EpochNumber(converter.get_epoch_by_slot(l_ref_slot) + converter.frame_config.epochs_per_frame)
            )

        if l_ref_slot < last_processing_ref_slot:
            raise CSMError(f"Got invalid epochs range: {l_ref_slot=} < {last_processing_ref_slot=}")
        if l_ref_slot >= r_ref_slot:
            raise CSMError(f"Got invalid epochs range {r_ref_slot=}, {l_ref_slot=}")

        l_epoch = converter.get_epoch_by_slot(SlotNumber(l_ref_slot + 1))
        r_epoch = converter.get_epoch_by_slot(r_ref_slot)

        # Update Prometheus metrics
        CSM_CURRENT_FRAME_RANGE_L_EPOCH.set(l_epoch)
        CSM_CURRENT_FRAME_RANGE_R_EPOCH.set(r_epoch)

        return l_epoch, r_epoch

    def converter(self, blockstamp: BlockStamp) -> Web3Converter:
        return Web3Converter(self.get_chain_config(blockstamp), self.get_frame_config(blockstamp))
