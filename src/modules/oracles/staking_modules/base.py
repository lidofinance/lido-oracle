import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import batched

from hexbytes import HexBytes

from src import variables
from src.constants import UINT64_MAX
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.duration_meter import duration_meter
from src.metrics.prometheus.performance_oracle import (
    PERFORMANCE_ORACLE_LAST_RANGE_CHECK_UNIXTIME,
    PERFORMANCE_ORACLE_TARGET_L_EPOCH,
    PERFORMANCE_ORACLE_TARGET_R_EPOCH,
    PERFORMANCE_ORACLE_WAITING_FOR_DATA,
)
from src.modules.common.types import ZERO_HASH, ModuleExecuteDelay
from src.modules.oracles.common.oracle_module import OracleModule
from src.modules.oracles.staking_modules.common.distribution import Distribution, DistributionResult
from src.modules.oracles.staking_modules.common.helpers.last_report import LastReport
from src.modules.oracles.staking_modules.common.log import Logs
from src.modules.oracles.staking_modules.common.state import State
from src.modules.oracles.staking_modules.common.tree import RewardsTree, StrikesTree, Tree
from src.modules.oracles.staking_modules.common.types import ReportData, RewardsShares, StrikesList, StrikesValidator
from src.providers.execution.contracts.cs_fee_oracle import CSFeeOracleContract
from src.providers.execution.exceptions import InconsistentData
from src.providers.ipfs import CID
from src.types import (
    BlockStamp,
    EpochNumber,
    NodeOperatorId,
    ReferenceBlockStamp,
    SlotNumber,
    ValidatorIndex,
)
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.range import sequence
from src.utils.validator_state import is_active_validator
from src.web3py.extensions.telemetry_data_bus import TelemetryEventId
from src.web3py.types import Web3StakingModule


logger = logging.getLogger(__name__)


class SMPerformanceOracleError(Exception):
    """Unrecoverable error in staking module performance oracle"""


@dataclass
class ThrottledTelemetry:
    interval_seconds: int
    send_callback: Callable[[TelemetryEventId, dict], bool]
    last_sent_at: float | None = None
    last_payload: dict | None = None

    @property
    def elapsed_since_last_send(self) -> float:
        if self.last_sent_at is None:
            return sys.float_info.max
        return time.monotonic() - self.last_sent_at

    def send(self, payload: dict, *, ignore_cooldown: bool = False):
        if payload == self.last_payload:
            return

        interval_elapsed = self.elapsed_since_last_send >= self.interval_seconds
        if not (ignore_cooldown or interval_elapsed):
            return

        self.last_sent_at = time.monotonic()
        self.last_payload = payload
        self.send_callback(TelemetryEventId.DIAGNOSTIC, payload)


class SMPerformanceOracle(OracleModule[Web3StakingModule]):
    """
    Staking Module performance oracle collects performance of staking module node operators and creates a Merkle tree
    of the resulting distribution of shares among the operators.

    The algorithm for calculating performance includes the following steps:
        1. Collect duties of the network validators for the frame.
        2. Calculate the performance of each validator based on their duties.
        3. Calculate the share of each node operator excluding underperforming validators.
    """

    COMPATIBLE_CONTRACT_VERSION: int = 0
    COMPATIBLE_CONSENSUS_VERSION: int = 0

    report_contract: CSFeeOracleContract
    state: State

    def __init__(self, w3: Web3StakingModule):
        if self.COMPATIBLE_CONTRACT_VERSION == 0:
            raise ValueError("CONTRACT_VERSION is not defined")
        if self.COMPATIBLE_CONSENSUS_VERSION == 0:
            raise ValueError("CONSENSUS_VERSION is not defined")
        self.consumer = self.__class__.__name__
        self.report_contract = w3.staking_module.oracle
        self.state = State.load(self.consumer)
        self.collector_telemetry = ThrottledTelemetry(
            interval_seconds=variables.TELEMETRY_DIAGNOSTIC_INTERVAL_SECONDS,
            send_callback=self._try_send_telemetry,
        )
        super().__init__(w3)

    def refresh_contracts(self):
        self.w3.staking_module.reload_contracts()
        self.report_contract = self.w3.staking_module.oracle
        self.state.clear()

    def is_contracts_addresses_changed(self) -> bool:
        return self.w3.staking_module.has_contract_address_changed()

    # TODO: Do we really need to remove the demand, let's say for the case we have a bug in the oracle module but not in
    # the collector.
    def shutdown(self) -> None:
        performance_client = getattr(self.w3, "performance", None)
        if performance_client is None:
            logger.debug(
                {
                    "msg": "Performance client is not attached, skipping demand cleanup",
                    "consumer": self.consumer,
                }
            )
            return
        try:
            demand = performance_client.get_epochs_demand(self.consumer)
            if not demand:
                logger.info({"msg": "No demand on shutdown", "consumer": self.consumer})
                return
            performance_client.delete_epochs_demand(self.consumer)
            logger.info(
                {
                    "msg": "Cleared Performance Collector demand on shutdown",
                    "consumer": self.consumer,
                }
            )
        except (ConnectionError, TimeoutError, OSError) as error:
            logger.warning(
                {
                    "msg": "Unexpected error during Performance Collector demand cleanup",
                    "consumer": self.consumer,
                    "error": str(error),
                }
            )

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        if not self._check_compatibility(last_finalized_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self._prepare_to_collect(last_finalized_blockstamp)

        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)
        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        collected = self._collect_data()
        if not collected:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @duration_meter()
    def _prepare_to_collect(self, blockstamp: BlockStamp):
        l_epoch, r_epoch = self._get_epochs_range_to_process(blockstamp)
        converter = self._get_web3_converter(blockstamp)
        self.state.migrate(l_epoch, r_epoch, converter.frame_config.epochs_per_frame)
        self._post_epochs_demand(l_epoch, r_epoch)

    def _post_epochs_demand(self, l_epoch: EpochNumber, r_epoch: EpochNumber):
        range_available = self._check_range_availability(l_epoch, r_epoch)
        if range_available:
            PERFORMANCE_ORACLE_WAITING_FOR_DATA.labels(consumer=self.consumer).set(0)
            logger.info(
                {"msg": "Performance data range is already available", "start_epoch": l_epoch, "end_epoch": r_epoch}
            )
            return

        PERFORMANCE_ORACLE_WAITING_FOR_DATA.labels(consumer=self.consumer).set(1)

        current_demand = self.w3.performance.get_epochs_demand(self.consumer)
        current_epochs_range = (current_demand.from_epoch, current_demand.to_epoch) if current_demand else None
        if current_epochs_range != (l_epoch, r_epoch):
            logger.info(
                {
                    "msg": "Posting epochs demand for Performance Collector",
                    "consumer": self.consumer,
                    "old_range": current_epochs_range,
                    "new_range": (l_epoch, r_epoch),
                }
            )
            self.w3.performance.post_epochs_demand(self.consumer, l_epoch, r_epoch)

    def _collect_data(self) -> bool:
        logger.info({"msg": "Collecting data for the report from Performance Collector"})

        self.state.ensure_initialized()

        if not self.state.is_fulfilled:
            l_epoch, r_epoch = self.state.range
            range_available = self._check_range_availability(l_epoch, r_epoch)
            if not range_available:
                logger.warning(
                    {
                        "msg": "Performance data range is not available yet",
                        "start_epoch": l_epoch,
                        "end_epoch": r_epoch,
                    }
                )
                return False
            logger.info({"msg": "Performance data range is available", "start_epoch": l_epoch, "end_epoch": r_epoch})
            self._fulfill_state()

        return self.state.is_fulfilled

    def _check_range_availability(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> bool:
        PERFORMANCE_ORACLE_LAST_RANGE_CHECK_UNIXTIME.labels(consumer=self.consumer).set_to_current_time()
        range_available = self.w3.performance.is_range_available(l_epoch, r_epoch)
        self.collector_telemetry.send(
            {
                "l_epoch": l_epoch,
                "r_epoch": r_epoch,
                "ready": self.w3.performance.get_stored_epochs_count(l_epoch, r_epoch),
            },
            ignore_cooldown=range_available,
        )
        return range_available

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        self._validate_state(blockstamp)

        distribution, last_report = self._calculate_distribution(blockstamp)
        rewards_tree_root, rewards_cid = last_report.rewards_tree_root, last_report.rewards_tree_cid

        if distribution.total_rewards:
            rewards_tree = self._make_rewards_tree(distribution.total_rewards_map)
            rewards_tree_root = rewards_tree.root
            rewards_cid = self._publish_tree(rewards_tree)

        if distribution.strikes:
            strikes_tree = self._make_strikes_tree(distribution.strikes)
            strikes_tree_root = strikes_tree.root
            if strikes_tree_root == last_report.strikes_tree_root:
                logger.info({"msg": "Strikes tree is the same as the previous one"})
                strikes_cid = last_report.strikes_tree_cid
            else:
                strikes_cid = self._publish_tree(strikes_tree)
        else:
            strikes_tree_root = HexBytes(ZERO_HASH)
            strikes_cid = None

        logs_cid = self._publish_log(distribution.logs)

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
    def _calculate_distribution(self, blockstamp: ReferenceBlockStamp) -> tuple[DistributionResult, LastReport]:
        last_report = self._get_last_report(blockstamp)
        distribution = Distribution(self.w3, self._get_web3_converter(blockstamp), self.state)
        result = distribution.calculate(blockstamp, last_report)
        return result, last_report

    def is_main_data_submitted(self, blockstamp: BlockStamp) -> bool:
        last_ref_slot = self.w3.staking_module.get_last_processing_ref_slot(blockstamp)
        ref_slot = self.get_initial_or_current_frame(blockstamp).ref_slot
        return last_ref_slot == ref_slot

    def is_contract_reportable(self, blockstamp: BlockStamp) -> bool:
        return not self.is_main_data_submitted(blockstamp)

    def is_reporting_allowed(self, blockstamp: ReferenceBlockStamp) -> bool:
        on_pause = self.report_contract.is_paused('latest')
        CONTRACT_ON_PAUSE.labels(self.consumer).set(on_pause)
        return not on_pause

    def _validate_state(self, blockstamp: ReferenceBlockStamp) -> None:
        # NOTE: We cannot use `r_epoch` from the `current_frame_range` call because the `blockstamp` is a
        # `ReferenceBlockStamp`, hence it's a block the frame ends at. We use `ref_epoch` instead.
        l_epoch, _ = self._get_epochs_range_to_process(blockstamp)
        r_epoch = blockstamp.ref_epoch

        self.state.validate(l_epoch, r_epoch)

    @duration_meter()
    def _fulfill_state(self):  # noqa: C901
        finalized_blockstamp = self._receive_last_finalized_slot()
        validators = self.w3.cc.get_validators(finalized_blockstamp)

        batch_size = variables.PERFORMANCE_COLLECTOR_EPOCHS_BATCH_SIZE

        logger.info(
            {
                "msg": "Starting state fulfillment",
                "total_frames": len(self.state.frames),
                "total_validators": len(validators),
                "batch_size": batch_size,
            }
        )

        for l_epoch, r_epoch in self.state.frames:
            logger.info(
                {
                    "msg": "Processing frame",
                    "start_epoch": l_epoch,
                    "end_epoch": r_epoch,
                    "total_epochs": r_epoch - l_epoch + 1,
                }
            )

            for epochs_batch in batched(sequence(l_epoch, r_epoch), batch_size, strict=False):
                start_epoch, end_epoch = epochs_batch[0], epochs_batch[-1]
                unprocessed_epochs = self.state.unprocessed_epochs
                if not any(epoch in unprocessed_epochs for epoch in epochs_batch):
                    logger.debug(
                        {
                            "msg": "Batch epochs are already processed",
                            "start_epoch": start_epoch,
                            "end_epoch": end_epoch,
                        }
                    )
                    continue

                logger.info(
                    {
                        "msg": "Requesting performance data batch from collector",
                        "start_epoch": start_epoch,
                        "end_epoch": end_epoch,
                        "total_epochs": len(epochs_batch),
                    }
                )

                duties = self.w3.performance.get_epochs_data(start_epoch, end_epoch)
                duties_by_epoch = {duty.epoch: duty for duty in duties}

                for epoch in epochs_batch:
                    if epoch not in unprocessed_epochs:
                        logger.debug({"msg": f"Epoch {epoch} is already processed"})
                        continue

                    epoch_data = duties_by_epoch.get(int(epoch))
                    if epoch_data is None:
                        raise ValueError(f"Epoch {epoch} is missing in Performance Collector")

                    (
                        misses,
                        proposers,
                        props_flags,
                        syncs_vids,
                        syncs_misses,
                    ) = (
                        set(ValidatorIndex(vid) for vid in epoch_data.attestations),  # XXX: set for performance reasons
                        [ValidatorIndex(vid) for vid in epoch_data.proposals_vids],
                        epoch_data.proposals_flags,  # proposed or not status
                        [ValidatorIndex(vid) for vid in epoch_data.syncs_vids],
                        epoch_data.syncs_misses,  # count of missed blocks in sync duties
                    )

                    if len(proposers) != len(props_flags) or len(syncs_vids) != len(syncs_misses):
                        raise ValueError(
                            f"Epoch {epoch} data is corrupted: "
                            f"{len(proposers)=}, {len(props_flags)=}, "
                            f"{len(syncs_vids)=}, {len(syncs_misses)=}"
                        )

                    logger.info(
                        {
                            "msg": "Performance data received",
                            "epoch": epoch,
                            "misses_count": len(misses),
                            "proposals_count": len(proposers),
                            "sync_duties_count": len(syncs_vids),
                        }
                    )

                    for validator in validators:
                        missed_att = validator.index in misses
                        if not is_active_validator(validator, epoch):
                            if missed_att:
                                raise ValueError(
                                    f"Validator {validator.index} missed attestation "
                                    f"in epoch {epoch}, but was not active"
                                )
                            continue
                        self.state.save_att_duty(epoch, validator.index, included=not missed_att)

                    blocks_in_epoch = 0

                    for i, vid in enumerate(proposers):
                        proposed = props_flags[i]
                        self.state.save_prop_duty(epoch, vid, included=proposed)
                        blocks_in_epoch += int(proposed)

                    if blocks_in_epoch:
                        for i, vid in enumerate(syncs_vids):
                            s_misses = syncs_misses[i]
                            s_fulfilled = max(0, blocks_in_epoch - s_misses)  # XXX: when it's the case?
                            # TODO: Update the State API, the tight loop is not needed here.
                            for _ in range(s_fulfilled):
                                self.state.save_sync_duty(epoch, vid, included=True)
                            for _ in range(s_misses):
                                self.state.save_sync_duty(epoch, vid, included=False)

                    self.state.add_processed_epoch(epoch)
                    unprocessed_epochs.discard(epoch)
                # No need to commit the state on every epoch, it's enough to commit it once per batch.
                self.state.commit()

    def _make_rewards_tree(self, shares: dict[NodeOperatorId, RewardsShares]) -> RewardsTree:
        if not shares:
            raise ValueError("No shares to build a tree")
        _shares = shares.copy()

        stone = NodeOperatorId(self.w3.staking_module.module.MAX_OPERATORS_COUNT)

        if len(_shares) == 1:
            # XXX: We put a stone here to make sure that even with only 1 node
            # operator in the tree, it's still possible to claim rewards.
            # The CSModule contract skips pulling rewards if the proof's length is
            # zero, which is the case
            # when the tree has only one leaf.
            _shares[stone] = 0

        # XXX: Remove the stone as soon as we have enough leafs to build a suitable tree.
        if len(_shares) > 2 and stone in _shares:
            _shares.pop(stone)

        tree = RewardsTree.new(tuple(_shares.items()))
        logger.info({"msg": "New rewards tree built for the report", "root": repr(tree.root)})
        return tree

    def _make_strikes_tree(self, strikes: dict[StrikesValidator, StrikesList]) -> StrikesTree:
        if not strikes:
            raise ValueError("No strikes to build a tree")
        tree = StrikesTree.new(tuple((no_id, pubkey, strikes) for ((no_id, pubkey), strikes) in strikes.items()))
        logger.info({"msg": "New strikes tree built for the report", "root": repr(tree.root)})
        return tree

    def _publish_tree(self, tree: Tree) -> CID:
        tree_cid = self.w3.ipfs.publish(tree.encode())
        logger.info({"msg": "Tree dump uploaded to IPFS", "cid": repr(tree_cid)})
        return tree_cid

    def _publish_log(self, logs: Logs) -> CID:
        log_cid = self.w3.ipfs.publish(logs.encode())
        logger.info({"msg": "Frame(s) log uploaded to IPFS", "cid": repr(log_cid)})
        return log_cid

    @lru_cache(maxsize=1)
    def _get_epochs_range_to_process(self, blockstamp: BlockStamp) -> tuple[EpochNumber, EpochNumber]:
        converter = self._get_web3_converter(blockstamp)

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
        PERFORMANCE_ORACLE_TARGET_L_EPOCH.labels(consumer=self.consumer).set(int(l_epoch))
        PERFORMANCE_ORACLE_TARGET_R_EPOCH.labels(consumer=self.consumer).set(int(r_epoch))

        logger.info({"msg": "Epochs range for the report", "l_epoch": l_epoch, "r_epoch": r_epoch})

        return l_epoch, r_epoch
