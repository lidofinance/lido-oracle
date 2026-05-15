import logging
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from eth_typing import HexAddress
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
from src.modules.oracles.staking_modules.common.state import NetworkDuties, State
from src.modules.oracles.staking_modules.common.tree import RewardsTree, StrikesTree, Tree
from src.modules.oracles.staking_modules.common.types import ReportData, RewardsShares, StrikesList, StrikesValidator
from src.modules.sidecars.performance.common.db import Duty
from src.providers.consensus.types import Validator
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

        sent = self.send_callback(TelemetryEventId.DIAGNOSTIC, payload)
        if sent:
            self.last_sent_at = time.monotonic()
            self.last_payload = payload


class SMPerformanceOracle(OracleModule[Web3StakingModule]):
    """
    Staking Module performance oracle collects performance of staking module node operators and creates a Merkle tree
    of the resulting distribution of shares among the operators.

    The algorithm for calculating performance includes the following steps:
        1. Collect duties of the network validators for the frame.
        2. Calculate the performance of each validator based on their duties.
        3. Calculate the share of each node operator excluding underperforming validators.
    """

    report_contract: CSFeeOracleContract
    consumer: HexAddress
    collector_telemetry: ThrottledTelemetry

    def __init__(self, w3: Web3StakingModule):
        self.report_contract = w3.staking_module.oracle
        self.consumer = self.report_contract.address
        self.collector_telemetry = ThrottledTelemetry(
            interval_seconds=variables.TELEMETRY_DIAGNOSTIC_INTERVAL_SECONDS,
            send_callback=self._try_send_telemetry,
        )
        super().__init__(w3)

    def refresh_contracts(self):
        old_consumer = self.consumer
        self.w3.staking_module.reload_contracts()
        self.report_contract = self.w3.staking_module.oracle
        self.consumer = self.report_contract.address
        if self.consumer != old_consumer:
            with suppress(self.w3.performance.PROVIDER_EXCEPTION):
                self.w3.performance.delete_epochs_demand(old_consumer)

    def is_contracts_addresses_changed(self) -> bool:
        return self.w3.staking_module.has_contract_address_changed()

    def execute_module(self, last_finalized_blockstamp: BlockStamp) -> ModuleExecuteDelay:
        if not self._check_compatibility(last_finalized_blockstamp):
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.push_epochs_demand(last_finalized_blockstamp)

        report_blockstamp = self.get_blockstamp_for_report(last_finalized_blockstamp)
        if not report_blockstamp:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        is_range_available = self.check_report_range_availability(report_blockstamp)
        if not is_range_available:
            return ModuleExecuteDelay.NEXT_FINALIZED_EPOCH

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @duration_meter()
    def push_epochs_demand(self, blockstamp: BlockStamp) -> None:
        l_epoch, r_epoch = self._get_predicted_range(blockstamp)
        is_range_available = self._check_range_availability(l_epoch, r_epoch)
        if is_range_available:
            return

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

    def check_report_range_availability(self, blockstamp: ReferenceBlockStamp) -> bool:
        l_epoch, r_epoch = self._get_report_range(blockstamp)
        is_available = self._check_range_availability(l_epoch, r_epoch)
        if not is_available:
            logger.info(
                {
                    "msg": "Performance data range for report is not available yet",
                    "start_epoch": l_epoch,
                    "end_epoch": r_epoch,
                }
            )
        return is_available

    def _check_range_availability(self, l_epoch: EpochNumber, r_epoch: EpochNumber) -> bool:
        PERFORMANCE_ORACLE_TARGET_L_EPOCH.labels(consumer=self.consumer).set(l_epoch)
        PERFORMANCE_ORACLE_TARGET_R_EPOCH.labels(consumer=self.consumer).set(r_epoch)

        PERFORMANCE_ORACLE_LAST_RANGE_CHECK_UNIXTIME.labels(consumer=self.consumer).set_to_current_time()
        stored_count = self.w3.performance.get_stored_epochs_count(l_epoch, r_epoch)
        range_available = stored_count == (r_epoch - l_epoch + 1)
        self.collector_telemetry.send(
            {
                "l_epoch": l_epoch,
                "r_epoch": r_epoch,
                "ready": stored_count,
            },
            ignore_cooldown=range_available,
        )
        if range_available:
            PERFORMANCE_ORACLE_WAITING_FOR_DATA.labels(consumer=self.consumer).set(0)
            logger.info(
                {"msg": "Performance data range is already available", "start_epoch": l_epoch, "end_epoch": r_epoch}
            )
        else:
            PERFORMANCE_ORACLE_WAITING_FOR_DATA.labels(consumer=self.consumer).set(1)
        return range_available

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
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
            if (strikes_cid == last_report.strikes_tree_cid) != (strikes_tree_root == last_report.strikes_tree_root):
                raise ValueError(f"Invalid strikes tree built: {strikes_cid=}, {strikes_tree_root=}")
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

    @lru_cache(maxsize=1)
    def _calculate_distribution(self, blockstamp: ReferenceBlockStamp) -> tuple[DistributionResult, LastReport]:
        state = self._prepare_duties_state(blockstamp)
        last_report = self._get_last_report(blockstamp)

        distribution = Distribution(self.w3, self._get_web3_converter(blockstamp), state)
        result = distribution.calculate(blockstamp, last_report)

        return result, last_report

    def _prepare_duties_state(self, blockstamp: ReferenceBlockStamp) -> State:
        l_epoch, r_epoch = self._get_report_range(blockstamp)

        is_data_available = self._check_range_availability(l_epoch, r_epoch)
        if not is_data_available:
            raise ValueError(f"Performance data range is not available yet, but it should: {l_epoch=}, {r_epoch=}")

        converter = self._get_web3_converter(blockstamp)
        return self._get_duties_state(l_epoch, r_epoch, converter.frame_config.epochs_per_frame)

    def _get_last_report(self, blockstamp: ReferenceBlockStamp) -> LastReport:
        current_frame = self.get_frame_number_by_slot(blockstamp)
        return LastReport.load(self.w3, blockstamp, current_frame)

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

    @lru_cache(maxsize=1)
    @duration_meter()
    def _get_duties_state(
        self, report_l_epoch: EpochNumber, report_r_epoch: EpochNumber, epochs_per_frame: int
    ) -> State:
        finalized_blockstamp = self._receive_last_finalized_slot()
        validators_by_index = self.w3.cc.get_validators_by_indexes(finalized_blockstamp)

        state = State(report_l_epoch, report_r_epoch, epochs_per_frame)
        logger.info(
            {
                "msg": "Starting state fulfillment",
                "total_frames": len(state.frames),
                "total_epochs": report_r_epoch - report_l_epoch + 1,
                "total_validators": len(validators_by_index),
            }
        )

        for l_epoch, r_epoch in state.frames:
            state.save_duties(
                (l_epoch, r_epoch),
                self._get_frame_duties(l_epoch, r_epoch, validators_by_index)
            )

        return state

    def _get_frame_duties(  # noqa: C901
        self, l_epoch: EpochNumber, r_epoch: EpochNumber, validators_by_index: dict[int, Validator]
    ) -> NetworkDuties:
        duties_to_save = NetworkDuties()
        missed_atts: defaultdict[ValidatorIndex, int] = defaultdict(int)
        processed_epochs: set[EpochNumber] = set()

        tota_epochs = r_epoch - l_epoch + 1

        logger.info(
            {"msg": "Processing frame", "start_epoch": l_epoch, "end_epoch": r_epoch, "total_epochs": tota_epochs}
        )

        raw_duties = self.w3.performance.get_epochs_data(l_epoch, r_epoch)
        for duties in raw_duties:
            self._validate_epoch_data(duties)

            epoch = EpochNumber(duties.epoch)
            if epoch in processed_epochs:
                raise ValueError(f"Duplicate epoch data for epoch {epoch}")

            blocks_in_epoch = 0

            for i, vid in enumerate(ValidatorIndex(vid) for vid in duties.proposals_vids):
                if vid not in validators_by_index:
                    raise ValueError(f"Validator {vid} is missing in validators list")
                proposed = duties.proposals_flags[i]
                v_prop = duties_to_save.proposals[vid]
                v_prop.assigned += 1
                v_prop.included += int(proposed)
                blocks_in_epoch += int(proposed)

            if blocks_in_epoch:
                for i, vid in enumerate(ValidatorIndex(vid) for vid in duties.syncs_vids):
                    if vid not in validators_by_index:
                        raise ValueError(f"Validator {vid} is missing in validators list")
                    s_misses = duties.syncs_misses[i]
                    if s_misses > blocks_in_epoch:
                        raise ValueError(
                            f"Inconsistent sync committee duties data: index={i}, {vid=}, "
                            f"{s_misses=} > {blocks_in_epoch=}"
                        )
                    v_sync = duties_to_save.syncs[vid]
                    v_sync.assigned += blocks_in_epoch
                    v_sync.included += blocks_in_epoch - s_misses

            for vid in (ValidatorIndex(vid) for vid in duties.missed_attestation_vids):
                validator = validators_by_index.get(vid)
                if validator is None:
                    raise ValueError(f"Validator {vid} is missing in validators on list")
                if not is_active_validator(validator, epoch):
                    raise ValueError(
                        f"Validator {validator.index} missed attestation in epoch {epoch}, but was not active"
                    )
                missed_atts[vid] += 1

            processed_epochs.add(epoch)

        if len(processed_epochs) != tota_epochs:
            raise ValueError(f"Invalid frame data: expected {tota_epochs} epochs, got {len(processed_epochs)} epochs")

        for validator in validators_by_index.values():
            assigned = self._count_active_epochs(validator, l_epoch, r_epoch)
            if not assigned:
                continue

            misses = missed_atts[validator.index]
            if misses > assigned:
                raise ValueError(
                    f"Invalid attestation duties data: validator={validator.index}, {misses=} > {assigned=}"
                )
            v_atts = duties_to_save.attestations[validator.index]
            v_atts.assigned += assigned
            v_atts.included += assigned - misses

        return duties_to_save

    @staticmethod
    def _validate_epoch_data(duty: Duty):
        if len(duty.missed_attestation_vids) != len(set(duty.missed_attestation_vids)):
            raise ValueError(f"Duplicate validator indices in missed attestation vids for epoch {duty.epoch}")

        proposals_vids_len = len(duty.proposals_vids)
        proposals_flags_len = len(duty.proposals_flags)
        if proposals_vids_len != proposals_flags_len:
            raise ValueError(f"Epoch {duty.epoch} data is corrupted: {proposals_vids_len=} != {proposals_flags_len=}")

        syncs_vids_len = len(duty.syncs_vids)
        syncs_misses_len = len(duty.syncs_misses)
        if syncs_vids_len != syncs_misses_len:
            raise ValueError(f"Epoch {duty.epoch} data is corrupted: {syncs_vids_len=} != {syncs_misses_len=}")

    @staticmethod
    def _count_active_epochs(validator: Validator, l_epoch: EpochNumber, r_epoch: EpochNumber) -> int:
        first_active_epoch = max(l_epoch, validator.validator.activation_epoch)
        last_active_epoch = min(r_epoch, validator.validator.exit_epoch - 1)

        # Validator activates after the range or exits before it.
        if first_active_epoch > last_active_epoch:
            return 0

        return last_active_epoch - first_active_epoch + 1

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
    def _get_predicted_range(self, blockstamp: BlockStamp) -> tuple[EpochNumber, EpochNumber]:
        l_epoch = self._get_l_epoch(blockstamp)
        r_epoch = self._predict_r_epoch(blockstamp)
        if l_epoch > r_epoch:
            raise SMPerformanceOracleError(f"Got invalid predicted epochs range: {l_epoch=}, {r_epoch=}")
        logger.info({"msg": "Predicted epochs range", "start_epoch": l_epoch, "end_epoch": r_epoch})
        return l_epoch, r_epoch

    @lru_cache(maxsize=1)
    def _get_report_range(self, blockstamp: ReferenceBlockStamp) -> tuple[EpochNumber, EpochNumber]:
        l_epoch = self._get_l_epoch(blockstamp)
        r_epoch = blockstamp.ref_epoch
        if l_epoch > r_epoch:
            raise SMPerformanceOracleError(f"Got invalid report epochs range: {l_epoch=}, {r_epoch=}")
        logger.info({"msg": "Report epochs range", "start_epoch": l_epoch, "end_epoch": r_epoch})
        return l_epoch, r_epoch

    def _get_l_epoch(self, blockstamp: BlockStamp) -> EpochNumber:
        converter = self._get_web3_converter(blockstamp)

        far_future_initial_epoch = converter.get_epoch_by_timestamp(UINT64_MAX)
        if converter.frame_config.initial_epoch == far_future_initial_epoch:
            raise ValueError("Oracle initial epoch is not set yet")

        l_ref_slot = last_processing_ref_slot = self.w3.staking_module.get_last_processing_ref_slot(blockstamp)

        if not last_processing_ref_slot:
            initial_ref_slot = self.get_initial_ref_slot(blockstamp)
            l_ref_slot = SlotNumber(initial_ref_slot - converter.slots_per_frame)
            if l_ref_slot < 0:
                raise SMPerformanceOracleError("Invalid frame configuration for the current network")

        if last_processing_ref_slot > blockstamp.slot_number:
            raise InconsistentData(f"{last_processing_ref_slot=} > {blockstamp.slot_number=}")

        return converter.get_epoch_by_slot(SlotNumber(l_ref_slot + 1))

    def _predict_r_epoch(self, blockstamp: BlockStamp) -> EpochNumber:
        converter = self._get_web3_converter(blockstamp)

        current_frame = converter.get_frame_by_slot(blockstamp.slot_number)
        return converter.get_epoch_by_slot(converter.get_frame_last_slot(current_frame))
