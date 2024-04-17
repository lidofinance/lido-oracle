import time
from functools import cached_property
import logging

from web3.types import BlockIdentifier

from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.csm.checkpoint import CheckpointsFactory
from src.modules.csm.typings import FramePerformance, ReportData
from src.modules.submodules.consensus import ConsensusModule
from src.modules.submodules.oracle_module import BaseModule, ModuleExecuteDelay
from src.typings import BlockStamp, ReferenceBlockStamp, SlotNumber, EpochNumber
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import NodeOperatorId, StakingModule, ValidatorsByNodeOperator
from src.web3py.typings import Web3

logger = logging.getLogger(__name__)


class CSFeeOracle(BaseModule, ConsensusModule):
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

    def __init__(self, w3: Web3):
        self.report_contract = w3.csm.oracle
        super().__init__(w3)
        self.frame_performance: FramePerformance | None = None
        # TODO: Feed the cache with the data about the attestations observed so far.

    def refresh_contracts(self):
        self.report_contract = self.w3.csm.oracle

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)

        collected = self._collect_data(last_finalized_blockstamp)

        if not collected:
            # The data is not fully collected yet, wait for the next epoch
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        assert self.frame_performance
        assert self.frame_performance.is_coherent

        # Get the current frame.
        last_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        ref_slot = self.get_current_frame(blockstamp).ref_slot

        # Get module's node operators.
        _ = self.module_validators_by_node_operators(blockstamp)
        # Read performance threshold value from somewhere (hardcoded?).
        _ = self.frame_performance.avg_perf * 0.95
        # Build the map of the current distribution operators.
        # _ = groupby(self.frame_performance.aggr_per_val, operators)
        # Exclude validators of operators with stuck keys.
        _ = self.w3.csm.get_csm_stuck_node_operators(
            self._slot_to_block_identifier(last_ref_slot),
            self._slot_to_block_identifier(ref_slot),
        )
        # Exclude underperforming validators.

        # Calculate share of each CSM node operator.
        _ = self._to_distribute(blockstamp)
        shares: tuple[tuple[NodeOperatorId, int]] = tuple()  # type: ignore

        # Load the previous tree if any.
        _ = self.w3.csm.get_csm_tree_cid(blockstamp)
        # leafs = []
        # if cid:
        #     leafs = parse_leafs(ipfs.get(cid))
        # Create a Merkle tree of the cumulative distribution of shares among the operators.

        return ReportData(
            self.CONSENSUS_VERSION,
            blockstamp.ref_slot,
            tree_root=b"",  # type: ignore
            tree_cid="",
            distributed=sum((s for (_, s) in shares)),
        ).as_tuple()

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        last_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(blockstamp)
        ref_slot = self.get_current_frame(blockstamp).ref_slot
        return last_ref_slot == ref_slot

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self._is_paused(blockstamp)
        CONTRACT_ON_PAUSE.labels('csm').set(on_pause)
        logger.info({'msg': 'Fetch isPaused from CSM oracle contract.', 'value': on_pause})
        return not on_pause

    @cached_property
    def module(self) -> StakingModule:
        modules: list[StakingModule] = self.w3.lido_validators.get_staking_modules(self._receive_last_finalized_slot())

        for mod in modules:
            if mod.name == "":  # FIXME
                return mod

        raise ValueError("No CSM module found")

    @lru_cache(maxsize=1)
    def module_validators_by_node_operators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        return self.w3.lido_validators.get_module_validators_by_node_operators(self.module.id, blockstamp)

    def _is_paused(self, blockstamp: ReferenceBlockStamp) -> bool:
        return self.report_contract.functions.isPaused().call(block_identifier=blockstamp.block_hash)

    def _collect_data(self, last_finalized_blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection before the report ref slot and it's submission"""
        converter = Web3Converter(
            self.get_chain_config(last_finalized_blockstamp), self.get_frame_config(last_finalized_blockstamp)
        )

        l_ref_slot = self.w3.csm.get_csm_last_processing_ref_slot(last_finalized_blockstamp)
        r_ref_slot = self.get_current_frame(last_finalized_blockstamp).ref_slot

        # TODO: To think about the proper cache invalidation conditions.
        if self.frame_performance:
            if self.frame_performance.l_slot < l_ref_slot:
                self.frame_performance = None

        if not self.frame_performance:
            self.frame_performance = FramePerformance.try_read(r_ref_slot) or FramePerformance(
                l_slot=l_ref_slot, r_slot=r_ref_slot
            )

        # Finalized slot is the first slot of justifying epoch, so we need to take the previous
        finalized_epoch = EpochNumber(converter.get_epoch_by_slot(last_finalized_blockstamp.slot_number) - 1)

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
            checkpoint.process(last_finalized_blockstamp)
        delay = time.time() - start
        logger.info({"msg": f"All epochs processed in {delay:.2f} seconds"})

        self._print_result()
        return self.frame_performance.is_coherent

    def _print_result(self):
        assigned = 0
        inc = 0
        for _, aggr in self.frame_performance.aggr_per_val.items():
            assigned += aggr.assigned
            inc += aggr.included

        logger.info({"msg": f"Assigned: {assigned}"})
        logger.info({"msg": f"Included: {inc}"})

    def _to_distribute(self, blockstamp: ReferenceBlockStamp) -> int:
        return self.w3.csm.fee_distributor.pending_to_distribute(blockstamp.block_hash)

    def _slot_to_block_identifier(self, slot: SlotNumber) -> BlockIdentifier:
        block = self.w3.cc.get_block_details(slot)

        try:
            return block.message.body["execution_payload"]["block_hash"]
        except KeyError as e:
            raise ValueError(f"ExecutionPayload not found in slot {slot}") from e
