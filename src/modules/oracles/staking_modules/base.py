import atexit
import logging
from abc import abstractmethod

from hexbytes import HexBytes

from src.constants import UINT64_MAX
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.staking_module import (
    STAKING_MODULE_CURRENT_FRAME_RANGE_L_EPOCH,
    STAKING_MODULE_CURRENT_FRAME_RANGE_R_EPOCH,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.oracles.staking_modules.common.distribution import Distribution, DistributionResult
from src.modules.oracles.staking_modules.common.helpers.last_report import LastReport
from src.modules.oracles.staking_modules.common.log import Logs
from src.modules.oracles.staking_modules.common.state import State
from src.modules.oracles.staking_modules.common.tree import RewardsTree, StrikesTree, Tree
from src.modules.oracles.staking_modules.common.types import ReportData, RewardsShares, StrikesList, StrikesValidator
from src.modules.oracles.common.types import OracleModule
from src.modules.common.types import ZERO_HASH, ModuleExecuteDelay
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.exceptions import InconsistentData
from src.providers.ipfs import CID
from src.types import (
    BlockStamp,
    EpochNumber,
    ReferenceBlockStamp,
    SlotNumber,
    ValidatorIndex,
)
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.range import sequence
from src.utils.validator_state import is_active_validator
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import NodeOperatorId
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class SMPerformanceOracleError(Exception):
    """Unrecoverable error in staking module performance oracle"""


class SMPerformanceOracle(OracleModule):
    """
    Staking Module performance oracle collects performance of staking module node operators and creates a Merkle tree
    of the resulting distribution of shares among the operators. The root of the tree is then submitted to the
    module contract.

    The algorithm for calculating performance includes the following steps:
        1. Collect all the attestation duties of the network validators for the frame.
        2. Calculate the performance of each validator based on the attestations.
        3. Calculate the share of each node operator excluding underperforming validators.
    """

    @property
    @abstractmethod
    def COMPATIBLE_CONTRACT_VERSION(self) -> int:
        """Contract version this oracle is compatible with"""
        raise NotImplementedError

    @property
    @abstractmethod
    def COMPATIBLE_CONSENSUS_VERSION(self) -> int:
        """Consensus version this oracle is compatible with"""
        raise NotImplementedError

    report_contract: CSFeeOracleContract
    state: State

    def __init__(self, w3: Web3):
        self.consumer = self.__class__.__name__
        self.report_contract = w3.staking_module.oracle
        self.state = State.load(self.consumer)
        super().__init__(w3)
        atexit.register(self._on_shutdown)

    def refresh_contracts(self):
        self.report_contract = self.w3.staking_module.oracle
        self.w3.staking_module.reload_contracts()
        self.report_contract = self.w3.staking_module.oracle  # type: ignore
        self.state.clear()

    def is_contracts_addresses_changed(self) -> bool:
        return self.w3.staking_module.has_contract_address_changed()

    def _on_shutdown(self):
        performance_client = getattr(self.w3, "performance", None)
        if performance_client is None:
            logger.debug({
                "msg": "Performance client is not attached, skipping demand cleanup",
                "consumer": self.consumer,
            })
            return
        try:
            performance_client.delete_epochs_demand(self.consumer)
            logger.info({
                "msg": "Cleared Performance Collector demand on shutdown",
                "consumer": self.consumer,
            })
        except (ConnectionError, TimeoutError, OSError) as error:
            logger.warning({
                "msg": "Unexpected error during Performance Collector demand cleanup",
                "consumer": self.consumer,
                "error": str(error),
            })

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        if not self._check_compatability(last_finalized_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.set_epochs_range_to_collect(last_finalized_blockstamp)

        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)
        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        collected = self.collect_data()
        if not collected:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @duration_meter()
    def set_epochs_range_to_collect(self, blockstamp: BlockStamp):
        converter = self.converter(blockstamp)

        l_epoch, r_epoch = self.get_epochs_range_to_process(blockstamp)
        self.state.migrate(l_epoch, r_epoch, converter.frame_config.epochs_per_frame)
        self.state.log_progress()

        is_range_available = self.w3.performance.is_range_available(l_epoch, r_epoch)
        if is_range_available:
            logger.info({
                "msg": "Performance data range is already available",
                "start_epoch": l_epoch,
                "end_epoch": r_epoch
            })
            return

        current_demand = self.w3.performance.get_epochs_demand(self.consumer)
        current_epochs_range = (current_demand.l_epoch, current_demand.r_epoch) if current_demand else None
        if current_epochs_range != (l_epoch, r_epoch):
            logger.info({
                "msg": f"Updating {self.consumer} epochs demand for Performance Collector",
                "old": current_epochs_range,
                "new": (l_epoch, r_epoch)
            })
            self.w3.performance.post_epochs_demand(self.consumer, l_epoch, r_epoch)

    @duration_meter()
    def collect_data(self) -> bool:
        logger.info({"msg": "Collecting data for the report from Performance Collector"})

        self.state.ensure_initialized()

        if not self.state.is_fulfilled:
            for l_epoch, r_epoch in self.state.frames:
                is_data_range_available = self.w3.performance.is_range_available(
                    l_epoch, r_epoch
                )
                if not is_data_range_available:
                    logger.warning({
                        "msg": "Performance data range is not available yet",
                        "start_epoch": l_epoch,
                        "end_epoch": r_epoch
                    })
                    return False
                logger.info({
                    "msg": "Performance data range is available",
                    "start_epoch": l_epoch,
                    "end_epoch": r_epoch
                })
            self.fulfill_state()

        return self.state.is_fulfilled

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

    @lru_cache(maxsize=1)
    def calculate_distribution(self, blockstamp: ReferenceBlockStamp, last_report: LastReport) -> DistributionResult:
        distribution = Distribution(self.w3, self.converter(blockstamp), self.state)
        result = distribution.calculate(blockstamp, last_report)
        return result

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        last_ref_slot = self.w3.staking_module.get_last_processing_ref_slot(blockstamp)
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

    def fulfill_state(self):
        finalized_blockstamp = self._receive_last_finalized_slot()
        validators = self.w3.cc.get_validators(finalized_blockstamp)

        self.state.ensure_initialized()

        logger.info({
            "msg": "Starting state fulfillment",
            "total_frames": len(self.state.frames),
            "total_validators": len(validators)
        })

        for l_epoch, r_epoch in self.state.frames:
            logger.info({
                "msg": "Processing frame",
                "start_epoch": l_epoch,
                "end_epoch": r_epoch,
                "total_epochs": r_epoch - l_epoch + 1
            })

            for epoch in sequence(l_epoch, r_epoch):
                if epoch not in self.state.unprocessed_epochs:
                    logger.debug({"msg": f"Epoch {epoch} is already processed"})
                    continue

                logger.info({
                    "msg": "Requesting performance data from collector",
                    "epoch": epoch
                })
                epoch_data = self.w3.performance.get_epoch_data(epoch)
                if epoch_data is None:
                    raise ValueError(f"Epoch {epoch} is missing in Performance Collector")

                (
                    misses_raw,
                    props_vids,
                    props_flags,
                    syncs_vids,
                    syncs_misses,
                ) = (
                    [ValidatorIndex(vid) for vid in epoch_data.attestations],
                    [ValidatorIndex(vid) for vid in epoch_data.proposals_vids],
                    epoch_data.proposals_flags,  # proposed or not status
                    [ValidatorIndex(vid) for vid in epoch_data.syncs_vids],
                    epoch_data.syncs_misses,  # count of missed blocks in sync duties
                )

                if len(props_vids) != len(props_flags) or len(syncs_vids) != len(syncs_misses):
                    raise ValueError(f"Epoch {epoch} data is corrupted: {len(props_vids)=}, {len(props_flags)=}, {len(syncs_vids)=}, {len(syncs_misses)=}")

                logger.info({
                    "msg": "Performance data received",
                    "epoch": epoch,
                    "misses_count": len(misses_raw),
                    "proposals_count": len(props_vids),
                    "sync_duties_count": len(syncs_vids)
                })

                misses = set(misses_raw)
                for validator in validators:
                    missed_att = validator.index in misses
                    included_att = validator.index not in misses
                    is_active = is_active_validator(validator, epoch)
                    if not is_active and missed_att:
                        raise ValueError(f"Validator {validator.index} missed attestation in epoch {epoch}, but was not active")
                    self.state.save_att_duty(EpochNumber(epoch), validator.index, included=included_att)

                blocks_in_epoch = 0

                for i, vid in enumerate(props_vids):
                    proposed = props_flags[i]
                    self.state.save_prop_duty(EpochNumber(epoch), ValidatorIndex(vid), included=bool(proposed))
                    blocks_in_epoch += proposed

                if blocks_in_epoch:
                    for i, vid in enumerate(syncs_vids):
                        vid = ValidatorIndex(vid)
                        s_misses = syncs_misses[i]
                        s_fulfilled = max(0, blocks_in_epoch - s_misses)
                        for _ in range(s_fulfilled):
                            self.state.save_sync_duty(EpochNumber(epoch), vid, included=True)
                        for _ in range(s_misses):
                            self.state.save_sync_duty(EpochNumber(epoch), vid, included=False)

                self.state.add_processed_epoch(EpochNumber(epoch))
                self.state.log_progress()
                self.state.commit()

    def make_rewards_tree(self, shares: dict[NodeOperatorId, RewardsShares]) -> RewardsTree:
        if not shares:
            raise ValueError("No shares to build a tree")

        # XXX: We put a stone here to make sure, that even with only 1 node operator in the tree, it's still possible to
        # claim rewards. The CSModule contract skips pulling rewards if the proof's length is zero, which is the case
        # when the tree has only one leaf.
        stone = NodeOperatorId(self.w3.staking_module.module.MAX_OPERATORS_COUNT)
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

    def publish_log(self, logs: Logs) -> CID:
        log_cid = self.w3.ipfs.publish(logs.encode())
        logger.info({"msg": "Frame(s) log uploaded to IPFS", "cid": repr(log_cid)})
        return log_cid

    @lru_cache(maxsize=1)
    def get_epochs_range_to_process(self, blockstamp: BlockStamp) -> tuple[EpochNumber, EpochNumber]:
        converter = self.converter(blockstamp)

        far_future_initial_epoch = converter.get_epoch_by_timestamp(UINT64_MAX)
        if converter.frame_config.initial_epoch == far_future_initial_epoch:
            raise ValueError("Oracle initial epoch is not set yet")

        l_ref_slot = last_processing_ref_slot = self.w3.staking_module.get_last_processing_ref_slot(blockstamp)
        r_ref_slot = initial_ref_slot = self.get_initial_ref_slot(blockstamp)

        if last_processing_ref_slot > blockstamp.slot_number:
            raise InconsistentData(f"{last_processing_ref_slot=} > {blockstamp.slot_number=}")

        # The very first report, no previous ref slot.
        if not last_processing_ref_slot:
            l_ref_slot = SlotNumber(initial_ref_slot - converter.slots_per_frame)
            if l_ref_slot < 0:
                raise SMPerformanceOracleError("Invalid frame configuration for the current network")

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
            raise SMPerformanceOracleError(f"Got invalid epochs range: {l_ref_slot=} < {last_processing_ref_slot=}")
        if l_ref_slot >= r_ref_slot:
            raise SMPerformanceOracleError(f"Got invalid epochs range {r_ref_slot=}, {l_ref_slot=}")

        l_epoch = converter.get_epoch_by_slot(SlotNumber(l_ref_slot + 1))
        r_epoch = converter.get_epoch_by_slot(r_ref_slot)

        # Update Prometheus metrics
        STAKING_MODULE_CURRENT_FRAME_RANGE_L_EPOCH.set(l_epoch)
        STAKING_MODULE_CURRENT_FRAME_RANGE_R_EPOCH.set(r_epoch)

        logger.info({
            "msg": "Epochs range for the report",
            "l_epoch": l_epoch,
            "r_epoch": r_epoch
        })

        return l_epoch, r_epoch

    def converter(self, blockstamp: BlockStamp) -> Web3Converter:
        return Web3Converter(self.get_chain_config(blockstamp), self.get_frame_config(blockstamp))
