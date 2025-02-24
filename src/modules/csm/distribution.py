import logging
from collections import defaultdict
from functools import lru_cache

from src.modules.csm.log import FramePerfLog, OperatorFrameSummary
from src.modules.csm.state import DutyAccumulator, Frame, State
from src.modules.csm.types import Shares
from src.providers.execution.contracts.cs_parameters_registry import PerformanceCoefficients
from src.types import NodeOperatorId, ReferenceBlockStamp, EpochNumber, StakingModuleAddress
from src.utils.blockstamp import build_blockstamp
from src.utils.slot import get_reference_blockstamp, get_next_non_missed_slot
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import LidoValidator, ValidatorsByNodeOperator, StakingModule
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class Distribution:
    w3: Web3
    staking_module: StakingModule
    converter: Web3Converter
    state: State

    def __init__(self, w3: Web3, staking_module: StakingModule, converter: Web3Converter, state: State):
        self.w3 = w3
        self.staking_module = staking_module
        self.converter = converter
        self.state = state

    def calculate(
        self, blockstamp: ReferenceBlockStamp
    ) -> tuple[Shares, defaultdict[NodeOperatorId, Shares], Shares, list[FramePerfLog]]:
        """Computes distribution of fee shares at the given timestamp"""
        total_distributed_rewards = 0
        total_rewards_map = defaultdict[NodeOperatorId, int](int)
        total_rebate = 0
        logs: list[FramePerfLog] = []

        for frame in self.state.frames:
            logger.info({"msg": f"Calculating distribution for {frame=}"})
            _, to_epoch = frame
            frame_blockstamp = self._get_frame_blockstamp(blockstamp, to_epoch)
            frame_module_validators = self._get_module_validators(frame_blockstamp)

            total_rewards_to_distribute = self.w3.csm.fee_distributor.shares_to_distribute(frame_blockstamp.block_hash)
            rewards_to_distribute_in_frame = total_rewards_to_distribute - (total_distributed_rewards + total_rebate)

            rewards_in_frame, log = self._calculate_distribution_in_frame(
                frame, frame_blockstamp, rewards_to_distribute_in_frame, frame_module_validators
            )

            total_distributed_rewards += log.distributed_rewards
            total_rebate += log.rebate_to_protocol

            self.validate_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute)

            for no_id, rewards in rewards_in_frame.items():
                total_rewards_map[no_id] += rewards

            logs.append(log)

        return total_distributed_rewards, total_rewards_map, total_rebate, logs

    def _get_frame_blockstamp(self, blockstamp: ReferenceBlockStamp, to_epoch: EpochNumber) -> ReferenceBlockStamp:
        if to_epoch != blockstamp.ref_epoch:
            return self._get_ref_blockstamp_for_frame(blockstamp, to_epoch)
        return blockstamp

    def _get_ref_blockstamp_for_frame(
        self, blockstamp: ReferenceBlockStamp, frame_ref_epoch: EpochNumber
    ) -> ReferenceBlockStamp:
        return get_reference_blockstamp(
            cc=self.w3.cc,
            ref_slot=self.converter.get_epoch_last_slot(frame_ref_epoch),
            ref_epoch=frame_ref_epoch,
            last_finalized_slot_number=blockstamp.slot_number,
        )

    def _get_module_validators(self, blockstamp: ReferenceBlockStamp) -> ValidatorsByNodeOperator:
        return self.w3.lido_validators.get_module_validators_by_node_operators(
            StakingModuleAddress(self.w3.csm.module.address), blockstamp
        )

    def _calculate_distribution_in_frame(
        self,
        frame: Frame,
        blockstamp: ReferenceBlockStamp,
        rewards_to_distribute: int,
        operators_to_validators: ValidatorsByNodeOperator,
    ) -> tuple[dict[NodeOperatorId, int], FramePerfLog]:
        total_rebate_share = 0
        participation_shares: defaultdict[NodeOperatorId, int] = defaultdict(int)
        log = FramePerfLog(blockstamp, frame)

        network_perf = self._get_network_performance(frame)

        stuck_operators = self._get_stuck_operators(frame, blockstamp)
        for (_, no_id), validators in operators_to_validators.items():
            logger.info({"msg": f"Calculating distribution for {no_id=}"})
            log_operator = log.operators[no_id]
            if no_id in stuck_operators:
                log_operator.stuck = True
                continue

            curve_id = self.w3.csm.accounting.get_bond_curve_id(no_id, blockstamp.block_hash)
            perf_coeffs, perf_leeway, reward_share = self._get_curve_params(curve_id, blockstamp)

            sorted_validators = sorted(validators, key=lambda v: v.index)
            for key_number, validator in enumerate(sorted_validators):
                key_threshold = max(network_perf - perf_leeway.get_for(key_number), 0)
                key_reward_share = reward_share.get_for(key_number)

                att_duty = self.state.data[frame].attestations.get(validator.index)
                prop_duty = self.state.data[frame].proposals.get(validator.index)
                sync_duty = self.state.data[frame].syncs.get(validator.index)

                # TODO: better naming
                validator_rebate = self.process_validator_duties(
                    validator,
                    att_duty,
                    prop_duty,
                    sync_duty,
                    key_threshold,
                    key_reward_share,
                    perf_coeffs,
                    participation_shares,
                    log_operator,
                )
                total_rebate_share += validator_rebate

        rewards_distribution = self.calc_rewards_distribution_in_frame(
            participation_shares, total_rebate_share, rewards_to_distribute
        )

        for no_id, no_rewards in rewards_distribution.items():
            log.operators[no_id].distributed = no_rewards

        log.distributable = rewards_to_distribute
        log.distributed_rewards = sum(rewards_distribution.values())
        log.rebate_to_protocol = rewards_to_distribute - log.distributed_rewards

        return rewards_distribution, log

    @lru_cache()
    def _get_curve_params(self, curve_id: int, blockstamp: ReferenceBlockStamp):
        perf_coeffs = self.w3.csm.params.get_performance_coefficients(curve_id, blockstamp.block_hash)
        perf_leeway_data = self.w3.csm.params.get_performance_leeway_data(curve_id, blockstamp.block_hash)
        reward_share_data = self.w3.csm.params.get_reward_share_data(curve_id, blockstamp.block_hash)
        return perf_coeffs, perf_leeway_data, reward_share_data

    def _get_network_performance(self, frame: Frame) -> float:
        att_perf = self.state.get_att_network_aggr(frame)
        prop_perf = self.state.get_prop_network_aggr(frame)
        sync_perf = self.state.get_sync_network_aggr(frame)
        network_perf = PerformanceCoefficients().calc_performance(att_perf, prop_perf, sync_perf)
        return network_perf

    def _get_stuck_operators(self, frame: Frame, frame_blockstamp: ReferenceBlockStamp) -> set[NodeOperatorId]:
        l_epoch, _ = frame
        l_ref_slot = self.converter.get_epoch_first_slot(l_epoch)
        # NOTE: r_block is guaranteed to be <= ref_slot, and the check
        # in the inner frames assures the  l_block <= r_block.
        l_blockstamp = build_blockstamp(
            get_next_non_missed_slot(
                self.w3.cc,
                l_ref_slot,
                frame_blockstamp.slot_number,
            )
        )

        digests = self.w3.lido_contracts.staking_router.get_all_node_operator_digests(
            self.staking_module, l_blockstamp.block_hash
        )
        if not digests:
            logger.warning("No CSM digest at blockstamp=%s, module was not added yet?", l_blockstamp)
        stuck_from_digests = (no.id for no in digests if no.stuck_validators_count > 0)
        stuck_from_events = self.w3.csm.get_operators_with_stucks_in_range(
            l_blockstamp.block_hash,
            frame_blockstamp.block_hash,
        )
        return set(stuck_from_digests) | set(stuck_from_events)

    @staticmethod
    def process_validator_duties(
        validator: LidoValidator,
        attestation: DutyAccumulator | None,
        sync: DutyAccumulator | None,
        proposal: DutyAccumulator | None,
        threshold: float,
        reward_share: float,
        perf_coeffs: PerformanceCoefficients,
        participation_shares: defaultdict[NodeOperatorId, int],
        log_operator: OperatorFrameSummary,
    ) -> int:
        if attestation is None:
            # It's possible that the validator is not assigned to any duty, hence it's performance
            # is not presented in the aggregates (e.g. exited, pending for activation etc).
            # TODO: check `sync_aggr` to strike (in case of bad sync performance) after validator exit
            return 0

        log_validator = log_operator.validators[validator.index]

        log_validator.threshold = threshold
        log_validator.rewards_share = reward_share

        if validator.validator.slashed is True:
            # It means that validator was active during the frame and got slashed and didn't meet the exit
            # epoch, so we should not count such validator for operator's share.
            log_validator.slashed = True
            return 0

        performance = perf_coeffs.calc_performance(attestation, proposal, sync)

        log_validator.performance = performance
        log_validator.attestation_duty = attestation
        if proposal:
            log_validator.proposal_duty = proposal
        if sync:
            log_validator.sync_duty = sync

        if performance > threshold:
            # Count of assigned attestations used as a metrics of time the validator was active in the current frame.
            # Reward share is a share of the operator's reward the validator should get. It can be less than 1.
            participation_share = max(int(attestation.assigned * reward_share), 1)
            participation_shares[validator.lido_id.operatorIndex] += participation_share
            rebate_share = attestation.assigned - participation_share
            return rebate_share

        return 0

    @staticmethod
    def calc_rewards_distribution_in_frame(
        participation_shares: dict[NodeOperatorId, int],
        rebate_share: int,
        rewards_to_distribute: int,
    ) -> dict[NodeOperatorId, int]:
        rewards_distribution: dict[NodeOperatorId, int] = defaultdict(int)
        total_shares = rebate_share + sum(participation_shares.values())

        for no_id, no_participation_share in participation_shares.items():
            if no_participation_share == 0:
                # Skip operators with zero participation
                continue
            rewards_distribution[no_id] = rewards_to_distribute * no_participation_share // total_shares

        return rewards_distribution

    @staticmethod
    def validate_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute):
        if (total_distributed_rewards + total_rebate) > total_rewards_to_distribute:
            raise ValueError(
                f"Invalid distribution: {total_distributed_rewards + total_rebate} > {total_rewards_to_distribute}"
            )
