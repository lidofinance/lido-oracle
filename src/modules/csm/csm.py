import logging
from collections import defaultdict
from typing import Iterable

from hexbytes import HexBytes
from copy import deepcopy

from src.constants import TOTAL_BASIS_POINTS, UINT64_MAX
from src.metrics.prometheus.business import CONTRACT_ON_PAUSE
from src.metrics.prometheus.csm import (
    CSM_CURRENT_FRAME_RANGE_L_EPOCH,
    CSM_CURRENT_FRAME_RANGE_R_EPOCH,
)
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.csm.checkpoint import FrameCheckpointProcessor, FrameCheckpointsIterator, MinStepIsNotReached
from src.modules.csm.log import FramePerfLog, OperatorFrameSummary
from src.modules.csm.state import AttestationsAccumulator, Frame, State
from src.modules.csm.tree import RewardsTree, StrikesTree, Tree
from src.modules.csm.types import ReportData, RewardsTreeLeaf, Shares, StrikesList
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
)
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.slot import get_reference_blockstamp
from src.utils.types import hex_str_to_bytes
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperatorId, StakingModule, ValidatorsByNodeOperator
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class NoModuleFound(Exception):
    """Raised if no module find in the StakingRouter by the provided address"""


class CSMError(Exception):
    """Unrecoverable error in CSM module"""


type StrikesValidator = tuple[NodeOperatorId, HexBytes]


class CSOracle(BaseModule, ConsensusModule):
    """
    CSM performance module collects performance of CSM node operators and creates a Merkle tree of the resulting
    distribution of shares among the operators. The root of the tree is then submitted to the module contract.

    The algorithm for calculating performance includes the following steps:
        1. Collect all the attestation duties of the network validators for the frame.
        2. Calculate the performance of each validator based on the attestations.
        3. Calculate the share of each CSM node operator excluding underperforming validators.
    """

    COMPATIBLE_ONCHAIN_VERSIONS = [(1, 1), (1, 2)]

    report_contract: CSFeeOracleContract
    staking_module: StakingModule

    def __init__(self, w3: Web3):
        self.report_contract = w3.csm.oracle
        self.state = State.load()
        super().__init__(w3)
        self.staking_module = self._get_staking_module()

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

        self.process_report(report_blockstamp)
        return ModuleExecuteDelay.NEXT_SLOT

    @lru_cache(maxsize=1)
    @duration_meter()
    def build_report(self, blockstamp: ReferenceBlockStamp) -> tuple:
        self.validate_state(blockstamp)

        prev_rewards_root = self.w3.csm.get_rewards_tree_root(blockstamp)
        prev_rewards_cid = self.w3.csm.get_rewards_tree_cid(blockstamp)

        if (prev_rewards_cid is None) != (prev_rewards_root == ZERO_HASH):
            raise InconsistentData(f"Got inconsistent previous tree data: {prev_rewards_root=} {prev_rewards_cid=}")

        prev_strikes_root = self.w3.csm.get_strikes_tree_root(blockstamp)
        prev_strikes_cid = self.w3.csm.get_strikes_tree_cid(blockstamp)

        if (prev_strikes_cid is None) != (prev_strikes_root == ZERO_HASH):
            raise InconsistentData(f"Got inconsistent previous tree data: {prev_strikes_root=} {prev_strikes_cid=}")

        total_distributed, total_rewards, strikes_per_frame, logs = self.calculate_distribution(blockstamp)
        log_cid = self.publish_log(logs)

        rewards_tree_root, rewards_cid = prev_rewards_root, prev_rewards_cid
        strikes_tree_root, strikes_cid = prev_strikes_root, prev_strikes_cid

        if total_distributed:
            if prev_rewards_cid and prev_rewards_root != ZERO_HASH:
                # Update cumulative amount of stETH shares for all operators.
                for no_id, accumulated_rewards in self.get_accumulated_rewards(prev_rewards_cid, prev_rewards_root):
                    total_rewards[no_id] += accumulated_rewards
            else:
                logger.info({"msg": "No previous distribution. Nothing to accumulate"})

            rewards_tree = self.make_rewards_tree(total_rewards)
            rewards_tree_root = rewards_tree.root
            rewards_cid = self.publish_tree(rewards_tree)

        historical_strikes = {}
        if prev_strikes_cid and prev_strikes_root != ZERO_HASH:
            historical_strikes = self.get_accumulated_strikes(prev_strikes_cid, prev_strikes_root)

        strikes = self._merge_strikes(
            historical_strikes,
            strikes_per_frame,
            blockstamp,
        )
        strikes_tree = self.make_strikes_tree(strikes)
        strikes_tree_root = strikes_tree.root
        strikes_cid = self.publish_tree(strikes_tree)

        return ReportData(
            self.get_consensus_version(blockstamp),
            blockstamp.ref_slot,
            tree_root=rewards_tree_root,
            tree_cid=rewards_cid or "",
            log_cid=log_cid,
            distributed=total_distributed,
            strikes_tree_root=strikes_tree_root,
            strikes_tree_cid=strikes_cid or "",
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
        l_epoch, _ = self.get_epochs_range_to_process(blockstamp)
        r_epoch = blockstamp.ref_epoch

        self.state.validate(l_epoch, r_epoch)

    def collect_data(self, blockstamp: BlockStamp) -> bool:
        """Ongoing report data collection for the estimated reference slot"""

        consensus_version = self.get_consensus_version(blockstamp)
        eip7549_supported = consensus_version != 1

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

        self.state.migrate(l_epoch, r_epoch, converter.frame_config.epochs_per_frame, consensus_version)
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

        processor = FrameCheckpointProcessor(self.w3.cc, self.state, converter, blockstamp, eip7549_supported)

        for checkpoint in checkpoints:
            if self.get_epochs_range_to_process(self._receive_last_finalized_slot()) != (l_epoch, r_epoch):
                logger.info({"msg": "Checkpoints were prepared for an outdated epochs range, stop processing"})
                raise ValueError("Outdated checkpoint")
            processor.exec(checkpoint)

        return self.state.is_fulfilled

    def calculate_distribution(
        self,
        blockstamp: ReferenceBlockStamp,
    ) -> tuple[
        Shares,
        defaultdict[NodeOperatorId, Shares],
        dict[Frame, dict[StrikesValidator, int]],
        list[FramePerfLog],
    ]:
        """Computes distribution of fee shares at the given timestamp"""
        operators_to_validators = self.module_validators_by_node_operators(blockstamp)

        total_distributed = Shares(0)
        total_rewards = defaultdict[NodeOperatorId, Shares](Shares)
        strikes_per_frame: dict[Frame, dict[StrikesValidator, int]] = {}
        logs: list[FramePerfLog] = []

        for frame in self.state.frames:
            from_epoch, to_epoch = frame
            logger.info({"msg": f"Calculating distribution for frame [{from_epoch};{to_epoch}]"})

            frame_blockstamp = blockstamp
            if to_epoch != blockstamp.ref_epoch:
                frame_blockstamp = self._get_ref_blockstamp_for_frame(blockstamp, to_epoch)

            total_rewards_to_distribute = self.w3.csm.fee_distributor.shares_to_distribute(frame_blockstamp.block_hash)
            rewards_to_distribute_in_frame = total_rewards_to_distribute - total_distributed

            frame_threshold = self._get_performance_threshold(frame, blockstamp)
            log = FramePerfLog(blockstamp, frame, frame_threshold)

            rewards_in_frame, strikes_in_frame = self._calculate_distribution_in_frame(
                frame,
                frame_threshold,
                rewards_to_distribute_in_frame,
                operators_to_validators,
                log,
            )
            distributed_in_frame = sum(rewards_in_frame.values())
            if not distributed_in_frame:
                logger.info({"msg": f"No rewards distributed in frame [{from_epoch};{to_epoch}]"})

            strikes_per_frame[frame] = strikes_in_frame
            if not strikes_in_frame:
                logger.info({"msg": f"No strikes in frame [{from_epoch};{to_epoch}]"})

            total_distributed += distributed_in_frame
            if total_distributed > total_rewards_to_distribute:
                raise CSMError(f"Invalid distribution: {total_distributed=} > {total_rewards_to_distribute=}")

            for no_id, rewards in rewards_in_frame.items():
                total_rewards[no_id] += rewards

            logs.append(log)

        if total_distributed != sum(total_rewards.values()):
            raise InconsistentData(f"Invalid distribution: {sum(total_rewards.values())=} != {total_distributed=}")

        return total_distributed, total_rewards, strikes_per_frame, logs

    def _get_ref_blockstamp_for_frame(
        self, blockstamp: ReferenceBlockStamp, frame_ref_epoch: EpochNumber
    ) -> ReferenceBlockStamp:
        converter = self.converter(blockstamp)
        return get_reference_blockstamp(
            cc=self.w3.cc,
            ref_slot=converter.get_epoch_last_slot(frame_ref_epoch),
            ref_epoch=frame_ref_epoch,
            last_finalized_slot_number=blockstamp.slot_number,
        )

    def _calculate_distribution_in_frame(
        self,
        frame: Frame,
        threshold: float,
        rewards_to_distribute: int,
        operators_to_validators: ValidatorsByNodeOperator,
        log: FramePerfLog,
    ):
        participation_shares: defaultdict[NodeOperatorId, int] = defaultdict(int)
        strikes: dict[StrikesValidator, int] = {}

        for (_, no_id), validators in operators_to_validators.items():
            log_operator = log.operators[no_id]
            for validator in validators:
                duty = self.state.data[frame].get(validator.index)
                validator_strikes = self.process_validator_duty(
                    validator,
                    duty,
                    threshold,
                    participation_shares,
                    log_operator,
                )
                log_operator.validators[validator.index].strikes = validator_strikes
                if validator_strikes:
                    pubkey = HexBytes(hex_str_to_bytes(validator.validator.pubkey))
                    strikes[(no_id, pubkey)] = validator_strikes

        rewards_distribution = self.calc_rewards_distribution_in_frame(participation_shares, rewards_to_distribute)

        for no_id, no_rewards in rewards_distribution.items():
            log.operators[no_id].distributed = no_rewards

        log.distributable = rewards_to_distribute

        return rewards_distribution, strikes

    def _get_performance_threshold(self, frame: Frame, blockstamp: ReferenceBlockStamp) -> float:
        network_perf = self.state.get_network_aggr(frame).perf
        perf_leeway = self.w3.csm.oracle.perf_leeway_bp(blockstamp.block_hash) / TOTAL_BASIS_POINTS
        threshold = network_perf - perf_leeway
        return threshold

    @staticmethod
    def process_validator_duty(
        validator: LidoValidator,
        attestation_duty: AttestationsAccumulator | None,
        threshold: float,
        participation_shares: defaultdict[NodeOperatorId, int],
        log_operator: OperatorFrameSummary,
    ) -> int:
        if attestation_duty is None:
            # It's possible that the validator is not assigned to any duty, hence it's performance
            # is not presented in the aggregates (e.g. exited, pending for activation etc).
            # TODO: check `sync_aggr` to strike (in case of bad sync performance) after validator exit
            return 0

        log_validator = log_operator.validators[validator.index]
        log_validator.attestation_duty = attestation_duty

        if validator.validator.slashed is True:
            # It means that validator was active during the frame and got slashed and didn't meet the exit
            # epoch, so we should not count such validator for operator's share.
            log_validator.slashed = True
            return 1

        if attestation_duty.perf > threshold:
            # Count of assigned attestations used as a metrics of time
            # the validator was active in the current frame.
            participation_shares[validator.lido_id.operatorIndex] += attestation_duty.assigned
            return 0

        return 1

    @staticmethod
    def calc_rewards_distribution_in_frame(
        participation_shares: dict[NodeOperatorId, int],
        rewards_to_distribute: int,
    ) -> dict[NodeOperatorId, int]:
        if rewards_to_distribute < 0:
            raise ValueError(f"Invalid rewards to distribute: {rewards_to_distribute}")
        rewards_distribution: dict[NodeOperatorId, int] = defaultdict(int)
        total_participation = sum(participation_shares.values())

        for no_id, no_participation_share in participation_shares.items():
            if no_participation_share == 0:
                # Skip operators with zero participation
                continue
            rewards_distribution[no_id] = rewards_to_distribute * no_participation_share // total_participation

        return rewards_distribution

    def get_accumulated_rewards(self, cid: CID, root: HexBytes) -> Iterable[RewardsTreeLeaf]:
        logger.info({"msg": "Fetching tree by CID from IPFS", "cid": repr(cid)})
        tree = RewardsTree.decode(self.w3.ipfs.fetch(cid))

        logger.info({"msg": "Restored tree from IPFS dump", "root": repr(tree.root)})

        if tree.root != root:
            raise ValueError("Unexpected tree root got from IPFS dump")

        return tree.values

    def get_accumulated_strikes(self, cid: CID, root: HexBytes) -> dict[StrikesValidator, StrikesList]:
        logger.info({"msg": "Fetching tree by CID from IPFS", "cid": repr(cid)})
        tree = StrikesTree.decode(self.w3.ipfs.fetch(cid))

        logger.info({"msg": "Restored tree from IPFS dump", "root": repr(tree.root)})

        if tree.root != root:
            raise ValueError("Unexpected tree root got from IPFS dump")

        return {(no_id, pubkey): strikes for no_id, pubkey, strikes in tree.values}

    def _merge_strikes(
        self,
        historical_strikes: dict[StrikesValidator, StrikesList],
        strikes_per_frame: dict[Frame, dict[StrikesValidator, int]],
        blockstamp: ReferenceBlockStamp,
    ) -> dict[StrikesValidator, StrikesList]:
        out = deepcopy(historical_strikes)

        for frame in self.state.frames:
            strikes_in_frame = strikes_per_frame[frame]
            for key in strikes_in_frame:
                if key not in out:
                    out[key] = StrikesList()
                out[key].push(strikes_in_frame[key])

            _, to_epoch = frame
            frame_blockstamp = blockstamp
            if to_epoch != blockstamp.ref_epoch:
                frame_blockstamp = self._get_ref_blockstamp_for_frame(blockstamp, to_epoch)

            for key in out:
                no_id, _ = key
                if key not in strikes_in_frame:
                    out[key].push(StrikesList.SENTINEL)  # Just shifting...
                maxlen = self.w3.csm.get_strikes_params(no_id, frame_blockstamp).lifetime
                out[key].resize(maxlen)
                # NOTE: Cleanup sequences like [0,0,0] since they don't bring any information.
                if not sum(out[key]):
                    del out[key]

        return out

    def make_rewards_tree(self, shares: dict[NodeOperatorId, Shares]) -> RewardsTree:
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

        tree = RewardsTree.new(tuple((no_id, amount) for (no_id, amount) in shares.items()))
        logger.info({"msg": "New rewards tree built for the report", "root": repr(tree.root)})
        return tree

    def make_strikes_tree(self, strikes: dict[StrikesValidator, StrikesList]):
        if not strikes:
            raise ValueError("No strikes to build a tree")

        # XXX: We put a stone here to make sure, that even with only 1 validator in the tree, it's
        # still possible to report strikes. The CSStrikes contract reverts if the proof's length
        # is zero, which is the case when the tree has only one leaf.
        stone = (NodeOperatorId(self.w3.csm.module.MAX_OPERATORS_COUNT), HexBytes(b""))
        strikes[stone] = StrikesList()

        # XXX: Remove the stone as soon as we have enough leafs to build a suitable tree.
        if stone in strikes and len(strikes) > 2:
            strikes.pop(stone)

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

    def _get_staking_module(self) -> StakingModule:
        modules: list[StakingModule] = self.w3.lido_contracts.staking_router.get_staking_modules()

        for mod in modules:
            if mod.staking_module_address == self.w3.csm.module.address:
                return mod

        raise NoModuleFound
