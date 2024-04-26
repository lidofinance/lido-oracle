import logging
import time
from collections import defaultdict
from functools import cached_property

from web3.types import BlockIdentifier

from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.csm.checkpoint import CheckpointsFactory
from src.modules.csm.tree import Tree
from src.modules.csm.typings import FramePerformance, ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.modules.submodules.typings import ZERO_HASH
from src.providers.execution.contracts.CSFeeOracle import CSFeeOracle
from src.typings import BlockStamp, EpochNumber, ReferenceBlockStamp, SlotNumber, ValidatorIndex
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModule, ValidatorsByNodeOperator
from src.web3py.typings import Web3

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

    CONSENSUS_VERSION = 1
    CONTRACT_VERSION = 1

    report_contract: CSFeeOracle
    frame_performance: FramePerformance | None

    def __init__(self, w3: Web3):
        self.report_contract = w3.csm.oracle
        self.frame_performance = None
        super().__init__(w3)

    def refresh_contracts(self):
        self.report_contract = self.w3.csm.oracle  # type: ignore

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        collected = self._collect_data(last_finalized_blockstamp)
        if not collected:
            # The data is not fully collected yet, wait for the next epoch
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
        # pylint: disable=too-many-branches

        assert self.frame_performance
        assert self.frame_performance.is_coherent

        self._print_collect_result()

        threshold = self.frame_performance.avg_perf * self.w3.csm.oracle.perf_threshold(blockstamp.block_hash)
        stuck_operators = self.w3.csm.get_csm_stuck_node_operators(
            self._slot_to_block_identifier(self.frame_performance.l_slot),
            self._slot_to_block_identifier(self.frame_performance.r_slot),
        )

        operators = self.module_validators_by_node_operators(blockstamp)
        # Build the map of the current distribution operators.
        distribution: dict[NodeOperatorId, int] = {}
        for (_, no_id), validators in operators.items():
            if no_id in stuck_operators:
                continue

            portion = 0

            for v in validators:
                try:
                    perf = self.frame_performance.aggr_per_val[ValidatorIndex(int(v.index))].perf
                    if perf > threshold:
                        portion += 1
                except KeyError:
                    # It's possible that the validator is not assigned to any duty, hence it's performance
                    # is not presented in the aggregates (e.g. exited, pending for activation etc).
                    continue

            distribution[no_id] = portion

        # Calculate share of each CSM node operator.
        to_distribute = self.w3.csm.fee_distributor.pending_to_distribute(blockstamp.block_hash)
        shares: dict[NodeOperatorId, int] = defaultdict(int)
        total = sum(p for p in distribution.values())
        if total > 0:
            for no_id, portion in distribution.items():
                shares[no_id] = to_distribute * portion // total

        distributed = sum(s for s in shares.values())
        assert distributed <= to_distribute
        if not distributed:
            logger.info({"msg": "No shares distributed in the current frame"})

        # Load the previous tree if any.
        root = self.w3.csm.get_csm_tree_root(blockstamp)
        cid = self.w3.csm.get_csm_tree_cid(blockstamp)

        if cid:
            logger.info({"msg": "Fetching tree by CID from IPFS", "cid": cid})
            tree = Tree.decode(self.w3.ipfs.fetch(cid))

            logger.info({"msg": "Restored tree from IPFS dump", "root": repr(root)})

            if tree.root != root:
                raise ValueError("Unexpected tree root got from IPFS dump")

            # Update cumulative amount of shares for all operators.
            for v in tree.tree.values:
                no_id, amount = v["value"]
                shares[no_id] += amount

        if shares:
            if distributed:
                tree = Tree.new(tuple((no_id, amount) for (no_id, amount) in shares.items()))
                logger.info({"msg": "New tree built for the report", "root": repr(tree.root)})
                cid = self.w3.ipfs.upload(tree.encode())
                self.w3.ipfs.pin(cid)
                root = tree.root

        if root == ZERO_HASH:
            logger.info({"msg": "No fee distributed so far, and tree doesn't exist"})

        return ReportData(
            self.CONSENSUS_VERSION,
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
        modules: list[StakingModule] = self.w3.lido_validators.get_staking_modules(self._receive_last_finalized_slot())

        for mod in modules:
            if mod.staking_module_address == self.w3.csm.module.address:
                return mod

        raise ValueError("No CSM module found. Wrong address?")

    @lru_cache(maxsize=1)
    def module_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        return self.w3.lido_validators.get_module_validators_by_node_operators(self.module.id, blockstamp)

    def _collect_data(self, blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection before the report ref slot and it's submission"""
        logger.info({"msg": "Collecting data for the report"})
        converter = Web3Converter(self.get_chain_config(blockstamp), self.get_frame_config(blockstamp))

        r_ref_slot = self.get_current_frame(blockstamp).ref_slot
        l_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        if not l_ref_slot:
            # The very first report, no previous ref slot
            l_ref_slot = r_ref_slot - converter.get_epoch_last_slot(EpochNumber(converter.frame_config.epochs_per_frame))
        if l_ref_slot == r_ref_slot:
            # We are between reports, next report slot didn't happen yet. Predicting the next ref slot for the report
            # To calculate epochs range to collect the data
            r_ref_slot = converter.get_epoch_last_slot(EpochNumber(
                converter.get_epoch_by_slot(l_ref_slot) + converter.frame_config.epochs_per_frame
            ))

        logger.info({"msg": f"Frame for performance data collect: ({l_ref_slot};{r_ref_slot}]"})

        # TODO: To think about the proper cache invalidation conditions.
        if self.frame_performance:
            if self.frame_performance.l_slot < l_ref_slot:
                self.frame_performance = None

        if not self.frame_performance:
            self.frame_performance = FramePerformance.try_read(l_ref_slot) or FramePerformance(
                l_slot=l_ref_slot, r_slot=r_ref_slot
            )

        # Finalized slot is the first slot of justifying epoch, so we need to take the previous
        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(blockstamp.slot_number) - 1)

        l_epoch = EpochNumber(converter.get_epoch_by_slot(l_ref_slot) + 1)
        if l_epoch > finalized_epoch:
            return False
        r_epoch = converter.get_epoch_by_slot(r_ref_slot)

        factory = CheckpointsFactory(self.w3.cc, converter, self.frame_performance)
        checkpoints = factory.prepare_checkpoints(l_epoch, r_epoch, finalized_epoch)

        start = time.time()
        for checkpoint in checkpoints:
            if converter.get_epoch_by_slot(checkpoint.slot) > finalized_epoch:
                # checkpoint isn't finalized yet, can't be processed
                break
            logger.info({"msg": f"Processing checkpoint for slot {checkpoint.slot}"})
            logger.info({"msg": f"Processing {len(checkpoint.duty_epochs)} epochs"})
            checkpoint.process(blockstamp)
        logger.info({"msg": f"All epochs processed in {time.time() - start:.2f} seconds"})
        return self.frame_performance.is_coherent

    def _print_collect_result(self):
        assert self.frame_performance
        assigned = 0
        inc = 0
        for _, aggr in self.frame_performance.aggr_per_val.items():
            assigned += aggr.assigned
            inc += aggr.included

        logger.info({"msg": f"Assigned: {assigned}"})
        logger.info({"msg": f"Included: {inc}"})
        logger.info({"msg": f"Average performance: {self.frame_performance.avg_perf}"})

    def _slot_to_block_identifier(self, slot: SlotNumber) -> BlockIdentifier:
        block = self.w3.cc.get_block_details(slot)

        try:
            return block.message.body.execution_payload.block_hash
        except KeyError as e:
            raise ValueError(f"ExecutionPayload not found in slot {slot}") from e
