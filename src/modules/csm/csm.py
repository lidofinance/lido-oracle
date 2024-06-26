import logging
from collections import defaultdict
from functools import cached_property
from typing import Iterable

from src.constants import TOTAL_BASIS_POINTS, UINT64_MAX
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.csm.checkpoint import CheckpointProcessor, CheckpointsIterator, MinStepIsNotReached
from src.modules.csm.state import InvalidState, State
from src.modules.csm.tree import Tree
from src.modules.csm.types import ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.types import ZERO_HASH
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.types import BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber, StakingModuleAddress, ValidatorIndex
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.slot import get_first_non_missed_slot
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModule, ValidatorsByNodeOperator
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class CSOracle(BaseModule, ConsensusModule):
    """
    CSM performance module collects performance of CSM node operators and creates a Merkle tree of the resulting
    distribution of shares among the oprators. The root of the tree is then submitted to the module contract.

    The algorithm for calculating performance includes the following steps:
        1. Collect all the attestation duties of the network validators for the frame.
        2. Calculate the performance of each validator based on the attestations.
        3. Calculate the share of each CSM node operator excluding underperforming validators.
    """

    COMPATIBLE_CONTRACT_VERSIONS = [1]
    COMPATIBLE_CONSENSUS_VERSIONS = [1]

    report_contract: CSFeeOracleContract

    def __init__(self, w3: Web3):
        self.report_contract = w3.csm.oracle
        self.state = State.load()
        super().__init__(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.csm.oracle  # type: ignore

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

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        # pylint: disable=too-many-branches,too-many-statements

        l_epoch, r_epoch = self.current_frame_range(blockstamp)

        try:
            self.state.validate_for_report(l_epoch, r_epoch)
        except InvalidState as e:
            raise ValueError(f"State is not valid for the report. {e}") from e

        self.state.status()

        distributed, shares = self.calculate_distribution(blockstamp)
        if not distributed:
            logger.info({"msg": "No shares distributed in the current frame"})

        # Load the previous tree if any.
        root = self.w3.csm.get_csm_tree_root(blockstamp)
        cid = self.w3.csm.get_csm_tree_cid(blockstamp)

        if cid:
            logger.info({"msg": "Fetching tree by CID from IPFS", "cid": repr(cid)})
            tree = Tree.decode(self.w3.ipfs.fetch(cid))
            logger.info({"msg": "Restored tree from IPFS dump", "root": repr(root)})

            if tree.root != root:
                raise ValueError("Unexpected tree root got from IPFS dump")

            # Update cumulative amount of shares for all operators.
            for v in tree.tree.values:
                no_id, amount = v["value"]
                shares[no_id] += amount

        # XXX: We put a stone here to make sure, that even with only 1 node operator in the tree, it's still possible to
        # claim rewards. The CSModule contract skips pulling rewards if the proof's length is zero, which is the case
        # when the tree has only one leaf.
        stone = NodeOperatorId(self.w3.csm.module.MAX_OPERATORS_COUNT)
        if shares:
            shares[stone] = 0
        if stone in shares and len(shares) > 2:
            shares.pop(stone)

        if distributed:
            tree = Tree.new(tuple((no_id, amount) for (no_id, amount) in shares.items()))
            logger.info({"msg": "New tree built for the report", "root": repr(tree.root)})
            cid = self.w3.ipfs.publish(tree.encode())
            root = tree.root

        if root == ZERO_HASH:
            logger.info({"msg": "No fee distributed so far, and tree doesn't exist"})

        return ReportData(
            self.report_contract.get_consensus_version(blockstamp.block_hash),
            blockstamp.ref_slot,
            tree_root=root,
            tree_cid=cid,
            distributed=distributed,
        ).as_tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        last_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        ref_slot = self.get_current_frame(blockstamp).ref_slot
        return last_ref_slot == ref_slot

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp) and not self.w3.csm.module.is_paused()

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self.report_contract.is_paused(blockstamp.block_hash)
        CONTRACT_ON_PAUSE.labels("csm").set(on_pause)
        return not on_pause

    @cached_property
    def module(self) -> StakingModule:
        modules: list[StakingModule] = self.w3.lido_contracts.staking_router.get_staking_modules(
            self._receive_last_finalized_slot().block_hash
        )

        for mod in modules:
            if mod.staking_module_address == self.w3.csm.module.address:
                return mod

        raise ValueError("No CSM module found. Wrong address?")

    @lru_cache(maxsize=1)
    def module_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        return self.w3.lido_validators.get_module_validators_by_node_operators(
            StakingModuleAddress(self.module.staking_module_address), blockstamp
        )

    def collect_data(self, blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection before the report ref slot and it's submission"""
        logger.info({"msg": "Collecting data for the report"})

        converter = self.converter(blockstamp)

        l_epoch, r_epoch = self.current_frame_range(blockstamp)
        logger.info({"msg": f"Frame for performance data collect: epochs [{l_epoch};{r_epoch}]"})

        # Finalized slot is the first slot of justifying epoch, so we need to take the previous
        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(blockstamp.slot_number) - 1)
        if l_epoch > finalized_epoch:
            return False

        self.state.validate_for_collect(l_epoch, r_epoch)
        self.state.status()

        if done := self.state.is_fulfilled:
            logger.info({"msg": "All epochs are already processed. Nothing to collect"})
            return done

        try:
            checkpoints = CheckpointsIterator(
                converter, min(self.state.unprocessed_epochs) or l_epoch, r_epoch, finalized_epoch
            )
        except MinStepIsNotReached:
            return False

        processor = CheckpointProcessor(self.w3.cc, self.state, converter, blockstamp)

        for checkpoint in checkpoints:
            if self.current_frame_range(self._receive_last_finalized_slot()) != (l_epoch, r_epoch):
                logger.info({"msg": "Checkpoints were prepared for an outdated frame, stop processing"})
                raise ValueError("Outdated checkpoint")
            processor.exec(checkpoint)

        return self.state.is_fulfilled

    def calculate_distribution(self, blockstamp: ReferenceBlockStamp) -> tuple[int, defaultdict[NodeOperatorId, int]]:
        """Computes distribution of fee shares at the given timestamp"""

        threshold = self.state.avg_perf - self.w3.csm.oracle.perf_leeway_bp(blockstamp.block_hash) / TOTAL_BASIS_POINTS
        operators_to_validators = self.module_validators_by_node_operators(blockstamp)

        # Build the map of the current distribution operators.
        distribution: dict[NodeOperatorId, int] = defaultdict(int)
        stuck_operators = self.stuck_operators(blockstamp)
        for (_, no_id), validators in operators_to_validators.items():
            if no_id in stuck_operators:
                continue

            for v in validators:
                try:
                    aggr = self.state.data[ValidatorIndex(int(v.index))]
                except KeyError:
                    # It's possible that the validator is not assigned to any duty, hence it's performance
                    # is not presented in the aggregates (e.g. exited, pending for activation etc).
                    continue

                if aggr.perf > threshold:
                    # Count of assigned attestations used as a metrics of time
                    # the validator was active in the current frame.
                    distribution[no_id] += aggr.assigned

        # Calculate share of each CSM node operator.
        shares = defaultdict[NodeOperatorId, int](int)
        total = sum(p for p in distribution.values())

        if not total:
            return 0, shares

        to_distribute = self.w3.csm.fee_distributor.shares_to_distribute(blockstamp.block_hash)
        for no_id, no_share in distribution.items():
            if no_share:
                shares[no_id] = to_distribute * no_share // total

        distributed = sum(s for s in shares.values())
        assert distributed <= to_distribute
        return distributed, shares

    def stuck_operators(self, blockstamp: ReferenceBlockStamp) -> Iterable[NodeOperatorId]:
        l_epoch, _ = self.current_frame_range(blockstamp)
        l_ref_slot = self.converter(blockstamp).get_epoch_first_slot(l_epoch)
        # NOTE: r_block is guaranteed to be <= ref_slot, and the check
        # in the inner frames assures the  l_block <= r_block.
        return self.w3.csm.get_csm_stuck_node_operators(
            get_first_non_missed_slot(
                self.w3.cc,
                l_ref_slot,
                blockstamp.slot_number,
                direction='forward',
            ).message.body.execution_payload.block_hash,
            blockstamp.block_hash,
        )

    @lru_cache(maxsize=1)
    def current_frame_range(self, blockstamp: BlockStamp) -> tuple[EpochNumber, EpochNumber]:
        converter = self.converter(blockstamp)

        far_future_initial_epoch = converter.get_epoch_by_timestamp(UINT64_MAX)
        if converter.frame_config.initial_epoch == far_future_initial_epoch:
            raise ValueError("CSM oracle initial epoch is not set yet")

        l_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        r_ref_slot = self.get_current_frame(blockstamp).ref_slot

        # The very first report, no previous ref slot.
        if not l_ref_slot:
            l_ref_slot = SlotNumber(self.get_initial_ref_slot(blockstamp) - converter.slots_per_frame)
            if l_ref_slot < 0:
                raise ValueError("Invalid frame configuration for the current network")

        # We are between reports, next report slot didn't happen yet. Predicting the next ref slot for the report
        # to calculate epochs range to collect the data.
        if l_ref_slot == r_ref_slot:
            r_ref_slot = converter.get_epoch_last_slot(
                EpochNumber(converter.get_epoch_by_slot(l_ref_slot) + converter.frame_config.epochs_per_frame)
            )

        l_epoch = converter.get_epoch_by_slot(SlotNumber(l_ref_slot + 1))
        r_epoch = converter.get_epoch_by_slot(r_ref_slot)

        return l_epoch, r_epoch

    def converter(self, blockstamp: BlockStamp) -> Web3Converter:
        return Web3Converter(self.get_chain_config(blockstamp), self.get_frame_config(blockstamp))
