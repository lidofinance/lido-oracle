import logging
from collections import defaultdict
from typing import Iterator

from hexbytes import HexBytes

from src.constants import TOTAL_BASIS_POINTS, UINT64_MAX
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.csm import (
    CSM_CURRENT_FRAME_RANGE_L_EPOCH,
    CSM_CURRENT_FRAME_RANGE_R_EPOCH,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.csm.checkpoint import FrameCheckpointProcessor, FrameCheckpointsIterator, MinStepIsNotReached
from src.modules.csm.log import FramePerfLog
from src.modules.csm.state import State
from src.modules.csm.tree import Tree
from src.modules.csm.types import ReportData, Shares
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
    StakingModuleAddress,
    StakingModuleId,
)
from src.utils.blockstamp import build_blockstamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.slot import get_next_non_missed_slot
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModule, ValidatorsByNodeOperator
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class NoModuleFound(Exception):
    """Raised if no module find in the StakingRouter by the provided address"""


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

    COMPATIBLE_CONTRACT_VERSION = 1
    COMPATIBLE_CONSENSUS_VERSION = 2

    report_contract: CSFeeOracleContract
    module_id: StakingModuleId

    def __init__(self, w3: Web3):
        self.report_contract = w3.csm.oracle
        self.state = State.load()
        super().__init__(w3)
        self.module_id = self._get_module_id()

    def refresh_contracts(self):
        self.report_contract = self.w3.csm.oracle  # type: ignore
        self.state.clear()

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        collected = self.collect_data(last_finalized_blockstamp)
        if not collected:
            logger.info(
                {"msg": "Data required for the report is not fully collected yet. Waiting for the next finalized epoch"}
            )
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        # pylint:disable=duplicate-code
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)
        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        if not self._check_compatability(report_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        self.validate_state(blockstamp)

        prev_root = self.w3.csm.get_csm_tree_root(blockstamp)
        prev_cid = self.w3.csm.get_csm_tree_cid(blockstamp)

        if (prev_cid is None) != (prev_root == ZERO_HASH):
            raise InconsistentData(f"Got inconsistent previous tree data: {prev_root=} {prev_cid=}")

        distributed, shares, log = self.calculate_distribution(blockstamp)

        if distributed != sum(shares.values()):
            raise InconsistentData(f"Invalid distribution: {sum(shares.values())=} != {distributed=}")

        log_cid = self.publish_log(log)

        if not distributed and not shares:
            logger.info({"msg": "No shares distributed in the current frame"})
            return ReportData(
                consensus_version=self.get_consensus_version(blockstamp),
                ref_slot=blockstamp.ref_slot,
                tree_root=prev_root,
                tree_cid=prev_cid or "",
                log_cid=log_cid,
                distributed=0,
            ).as_tuple()

        if prev_cid and prev_root != ZERO_HASH:
            # Update cumulative amount of shares for all operators.
            for no_id, acc_shares in self.get_accumulated_shares(prev_cid, prev_root):
                shares[no_id] += acc_shares
        else:
            logger.info({"msg": "No previous distribution. Nothing to accumulate"})

        tree = self.make_tree(shares)
        tree_cid = self.publish_tree(tree)

        return ReportData(
            consensus_version=self.get_consensus_version(blockstamp),
            ref_slot=blockstamp.ref_slot,
            tree_root=tree.root,
            tree_cid=tree_cid,
            log_cid=log_cid,
            distributed=distributed,
        ).as_tuple()

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

    @lru_cache(maxsize=1)
    def module_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        return self.w3.lido_validators.get_module_validators_by_node_operators(
            StakingModuleAddress(self.w3.csm.module.address), blockstamp
        )

    def validate_state(self, blockstamp: ReferenceBlockStamp) -> None:
        # NOTE: We cannot use `r_epoch` from the `current_frame_range` call because the `blockstamp` is a
        # `ReferenceBlockStamp`, hence it's a block the frame ends at. We use `ref_epoch` instead.
        l_epoch, _ = self.current_frame_range(blockstamp)
        r_epoch = blockstamp.ref_epoch

        self.state.validate(l_epoch, r_epoch)

    def collect_data(self, blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection for the estimated reference slot"""

        consensus_version = self.get_consensus_version(blockstamp)

        logger.info({"msg": "Collecting data for the report"})

        converter = self.converter(blockstamp)

        l_epoch, r_epoch = self.current_frame_range(blockstamp)
        logger.info({"msg": f"Frame for performance data collect: epochs [{l_epoch};{r_epoch}]"})

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
                    "msg": f"Frame has been changed, but the change is not yet observed on finalized epoch {finalized_epoch}"
                }
            )
            return False

        if l_epoch > finalized_epoch:
            logger.info({"msg": "The starting epoch of the frame is not finalized yet"})
            return False

        self.state.migrate(l_epoch, r_epoch, consensus_version)
        self.state.log_progress()

        if self.state.is_fulfilled:
            logger.info({"msg": "All epochs are already processed. Nothing to collect"})
            return True

        try:
            checkpoints = FrameCheckpointsIterator(
                converter, min(self.state.unprocessed_epochs) or l_epoch, r_epoch, finalized_epoch
            )
        except MinStepIsNotReached:
            return False

        processor = FrameCheckpointProcessor(self.w3.cc, self.state, converter, blockstamp)

        for checkpoint in checkpoints:
            if self.current_frame_range(self._receive_last_finalized_slot()) != (l_epoch, r_epoch):
                logger.info({"msg": "Checkpoints were prepared for an outdated frame, stop processing"})
                raise ValueError("Outdated checkpoint")
            processor.exec(checkpoint)

        return self.state.is_fulfilled

    def calculate_distribution(
        self, blockstamp: ReferenceBlockStamp
    ) -> tuple[int, defaultdict[NodeOperatorId, int], FramePerfLog]:
        """Computes distribution of fee shares at the given timestamp"""

        network_avg_perf = self.state.get_network_aggr().perf
        threshold = network_avg_perf - self.w3.csm.oracle.perf_leeway_bp(blockstamp.block_hash) / TOTAL_BASIS_POINTS
        operators_to_validators = self.module_validators_by_node_operators(blockstamp)

        # Build the map of the current distribution operators.
        distribution: dict[NodeOperatorId, int] = defaultdict(int)
        stuck_operators = self.stuck_operators(blockstamp)
        log = FramePerfLog(blockstamp, self.state.frame, threshold)

        for (_, no_id), validators in operators_to_validators.items():
            if no_id in stuck_operators:
                log.operators[no_id].stuck = True
                continue

            for v in validators:
                aggr = self.state.data.get(v.index)

                if aggr is None:
                    # It's possible that the validator is not assigned to any duty, hence it's performance
                    # is not presented in the aggregates (e.g. exited, pending for activation etc).
                    continue

                if v.validator.slashed is True:
                    # It means that validator was active during the frame and got slashed and didn't meet the exit
                    # epoch, so we should not count such validator for operator's share.
                    log.operators[no_id].validators[v.index].slashed = True
                    continue

                if aggr.perf > threshold:
                    # Count of assigned attestations used as a metrics of time
                    # the validator was active in the current frame.
                    distribution[no_id] += aggr.assigned

                log.operators[no_id].validators[v.index].perf = aggr

        # Calculate share of each CSM node operator.
        shares = defaultdict[NodeOperatorId, int](int)
        total = sum(p for p in distribution.values())

        if not total:
            return 0, shares, log

        to_distribute = self.w3.csm.fee_distributor.shares_to_distribute(blockstamp.block_hash)
        log.distributable = to_distribute

        for no_id, no_share in distribution.items():
            if no_share:
                shares[no_id] = to_distribute * no_share // total
                log.operators[no_id].distributed = shares[no_id]

        distributed = sum(s for s in shares.values())
        if distributed > to_distribute:
            raise CSMError(f"Invalid distribution: {distributed=} > {to_distribute=}")
        return distributed, shares, log

    def get_accumulated_shares(self, cid: CID, root: HexBytes) -> Iterator[tuple[NodeOperatorId, Shares]]:
        logger.info({"msg": "Fetching tree by CID from IPFS", "cid": repr(cid)})
        tree = Tree.decode(self.w3.ipfs.fetch(cid))

        logger.info({"msg": "Restored tree from IPFS dump", "root": repr(tree.root)})

        if tree.root != root:
            raise ValueError("Unexpected tree root got from IPFS dump")

        for v in tree.tree.values:
            yield v["value"]

    def stuck_operators(self, blockstamp: ReferenceBlockStamp) -> set[NodeOperatorId]:
        stuck: set[NodeOperatorId] = set()
        l_epoch, _ = self.current_frame_range(blockstamp)
        l_ref_slot = self.converter(blockstamp).get_epoch_first_slot(l_epoch)
        # NOTE: r_block is guaranteed to be <= ref_slot, and the check
        # in the inner frames assures the  l_block <= r_block.
        l_blockstamp = build_blockstamp(
            get_next_non_missed_slot(
                self.w3.cc,
                l_ref_slot,
                blockstamp.slot_number,
            )
        )

        nos_by_module = self.w3.lido_validators.get_lido_node_operators_by_modules(l_blockstamp)
        if self.module_id in nos_by_module:
            stuck.update(no.id for no in nos_by_module[self.module_id] if no.stuck_validators_count > 0)
        else:
            logger.warning("No CSM digest at blockstamp=%s, module was not added yet?", l_blockstamp)

        stuck.update(
            self.w3.csm.get_operators_with_stucks_in_range(
                l_blockstamp.block_hash,
                blockstamp.block_hash,
            )
        )
        return stuck

    def make_tree(self, shares: dict[NodeOperatorId, Shares]) -> Tree:
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

        tree = Tree.new(tuple((no_id, amount) for (no_id, amount) in shares.items()))
        logger.info({"msg": "New tree built for the report", "root": repr(tree.root)})
        return tree

    def publish_tree(self, tree: Tree) -> CID:
        tree_cid = self.w3.ipfs.publish(tree.encode())
        logger.info({"msg": "Tree dump uploaded to IPFS", "cid": repr(tree_cid)})
        return tree_cid

    def publish_log(self, log: FramePerfLog) -> CID:
        log_cid = self.w3.ipfs.publish(log.encode())
        logger.info({"msg": "Frame log uploaded to IPFS", "cid": repr(log_cid)})
        return log_cid

    @lru_cache(maxsize=1)
    def current_frame_range(self, blockstamp: BlockStamp) -> tuple[EpochNumber, EpochNumber]:
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
            raise CSMError(f"Got invalid frame range: {l_ref_slot=} < {last_processing_ref_slot=}")
        if l_ref_slot >= r_ref_slot:
            raise CSMError(f"Got invalid frame range {r_ref_slot=}, {l_ref_slot=}")

        l_epoch = converter.get_epoch_by_slot(SlotNumber(l_ref_slot + 1))
        r_epoch = converter.get_epoch_by_slot(r_ref_slot)

        # Update Prometheus metrics
        CSM_CURRENT_FRAME_RANGE_L_EPOCH.set(l_epoch)
        CSM_CURRENT_FRAME_RANGE_R_EPOCH.set(r_epoch)

        return l_epoch, r_epoch

    def converter(self, blockstamp: BlockStamp) -> Web3Converter:
        return Web3Converter(self.get_chain_config(blockstamp), self.get_frame_config(blockstamp))

    def _get_module_id(self) -> StakingModuleId:
        modules: list[StakingModule] = self.w3.lido_contracts.staking_router.get_staking_modules()

        for mod in modules:
            if mod.staking_module_address == self.w3.csm.module.address:
                return mod.id

        raise NoModuleFound
