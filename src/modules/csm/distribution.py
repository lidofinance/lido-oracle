import logging
import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field

from src.modules.csm.helpers.last_report import LastReport
from src.modules.csm.log import FramePerfLog, OperatorFrameSummary
from src.modules.csm.state import Frame, State, ValidatorDuties
from src.modules.csm.types import (
    ParticipationShares,
    RewardsShares,
    StrikesList,
    StrikesValidator,
)
from src.providers.execution.contracts.cs_parameters_registry import (
    PerformanceCoefficients,
)
from src.providers.execution.exceptions import InconsistentData
from src.types import (
    EpochNumber,
    NodeOperatorId,
    ReferenceBlockStamp,
    StakingModuleAddress,
    ValidatorIndex,
)
from src.utils.slot import get_reference_blockstamp
from src.utils.web3converter import Web3Converter
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    ValidatorsByNodeOperator,
)
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


@dataclass
class ValidatorDutiesOutcome:
    participation_share: ParticipationShares
    rebate_share: ParticipationShares
    strikes: int


@dataclass
class DistributionResult:
    total_rewards: RewardsShares = 0
    total_rebate: RewardsShares = 0
    total_rewards_map: dict[NodeOperatorId, RewardsShares] = field(default_factory=lambda: defaultdict(RewardsShares))
    strikes: dict[StrikesValidator, StrikesList] = field(default_factory=lambda: defaultdict(StrikesList))
    logs: list[FramePerfLog] = field(default_factory=list)


class Distribution:
    w3: Web3
    converter: Web3Converter
    state: State

    def __init__(self, w3: Web3, converter: Web3Converter, state: State):
        self.w3 = w3
        self.converter = converter
        self.state = state

    def calculate(self, blockstamp: ReferenceBlockStamp, last_report: LastReport) -> DistributionResult:
        """Computes distribution of fee shares at the given timestamp"""
        result = DistributionResult()
        result.strikes.update(last_report.strikes.items())

        distributed_so_far = 0
        for frame in self.state.frames:
            from_epoch, to_epoch = frame
            logger.info({"msg": f"Calculating distribution for frame [{from_epoch};{to_epoch}]"})

            frame_blockstamp = self._get_frame_blockstamp(blockstamp, to_epoch)
            frame_module_validators = self._get_module_validators(frame_blockstamp)

            total_rewards_to_distribute = self.w3.csm.fee_distributor.shares_to_distribute(frame_blockstamp.block_hash)
            rewards_to_distribute_in_frame = total_rewards_to_distribute - distributed_so_far

            frame_log = FramePerfLog(frame_blockstamp, frame)
            (rewards_map_in_frame, distributed_rewards_in_frame, rebate_to_protocol_in_frame, strikes_in_frame) = (
                self._calculate_distribution_in_frame(
                    frame, frame_blockstamp, rewards_to_distribute_in_frame, frame_module_validators, frame_log
                )
            )
            if not distributed_rewards_in_frame:
                logger.info({"msg": f"No rewards distributed in frame [{from_epoch};{to_epoch}]"})

            result.strikes = self._process_strikes(result.strikes, strikes_in_frame, frame_blockstamp)
            if not strikes_in_frame:
                logger.info({"msg": f"No strikes in frame [{from_epoch};{to_epoch}]. Just shifting current strikes."})

            result.total_rewards += distributed_rewards_in_frame
            result.total_rebate += rebate_to_protocol_in_frame

            self.validate_distribution(result.total_rewards, result.total_rebate, total_rewards_to_distribute)
            distributed_so_far = result.total_rewards + result.total_rebate

            for no_id, rewards in rewards_map_in_frame.items():
                result.total_rewards_map[no_id] += rewards

            result.logs.append(frame_log)

        if result.total_rewards != sum(result.total_rewards_map.values()):
            raise InconsistentData(
                f"Invalid distribution: {sum(result.total_rewards_map.values())=} != {result.total_rewards=}"
            )

        for no_id, last_report_rewards in last_report.rewards:
            result.total_rewards_map[no_id] += last_report_rewards

        return result

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
        return self.w3.lido_validators.get_used_module_validators_by_node_operators(
            StakingModuleAddress(self.w3.csm.module.address), blockstamp
        )

    def _calculate_distribution_in_frame(
        self,
        frame: Frame,
        blockstamp: ReferenceBlockStamp,
        rewards_to_distribute: RewardsShares,
        operators_to_validators: ValidatorsByNodeOperator,
        log: FramePerfLog,
    ) -> tuple[dict[NodeOperatorId, RewardsShares], RewardsShares, RewardsShares, dict[StrikesValidator, int]]:
        total_rebate_share = 0
        participation_shares: dict[NodeOperatorId, dict[ValidatorIndex, ParticipationShares]] = {}
        frame_strikes: dict[StrikesValidator, int] = {}

        network_perf = self._get_network_performance(frame)

        for (_, no_id), validators in operators_to_validators.items():
            active_validators = [v for v in validators if self.state.data[frame].attestations[v.index].assigned > 0]
            if not active_validators:
                logger.info({"msg": f"No active validators for {no_id=} in the frame. Skipping"})
                continue

            logger.info({"msg": f"Calculating distribution for {no_id=}"})
            log_operator = log.operators[no_id]

            curve_params = self.w3.csm.get_curve_params(no_id, blockstamp)
            log_operator.performance_coefficients = curve_params.perf_coeffs

            active_validators.sort(key=lambda v: v.index)
            numbered_validators = enumerate(active_validators, 1)
            for key_number, validator in numbered_validators:
                key_threshold = max(network_perf - curve_params.perf_leeway_data.get_for(key_number), 0)
                key_reward_share = curve_params.reward_share_data.get_for(key_number)

                duties = self.state.get_validator_duties(frame, validator.index)

                validator_duties_outcome = self.get_validator_duties_outcome(
                    validator,
                    duties,
                    key_threshold,
                    key_reward_share,
                    curve_params.perf_coeffs,
                    log_operator,
                )
                if validator_duties_outcome.strikes:
                    frame_strikes[(no_id, validator.pubkey)] = validator_duties_outcome.strikes
                    log_operator.validators[validator.index].strikes = validator_duties_outcome.strikes
                if not participation_shares.get(no_id):
                    participation_shares[no_id] = {}
                participation_shares[no_id][validator.index] = validator_duties_outcome.participation_share

                total_rebate_share += validator_duties_outcome.rebate_share

        rewards_distribution_map = self.calc_rewards_distribution_in_frame(
            participation_shares, total_rebate_share, rewards_to_distribute, log
        )
        distributed_rewards = sum(rewards_distribution_map.values())
        # All rewards to distribute should not be rebated if no duties were assigned to validators or
        # all validators were below threshold.
        rebate_to_protocol = 0 if not distributed_rewards else rewards_to_distribute - distributed_rewards

        for no_id, no_rewards in rewards_distribution_map.items():
            log.operators[no_id].distributed_rewards = no_rewards
        log.distributable = rewards_to_distribute
        log.distributed_rewards = distributed_rewards
        log.rebate_to_protocol = rebate_to_protocol

        return rewards_distribution_map, distributed_rewards, rebate_to_protocol, frame_strikes

    def _get_network_performance(self, frame: Frame) -> float:
        att_aggr = self.state.get_att_network_aggr(frame)
        prop_aggr = self.state.get_prop_network_aggr(frame)
        sync_aggr = self.state.get_sync_network_aggr(frame)
        network_perf = PerformanceCoefficients().calc_performance(ValidatorDuties(att_aggr, prop_aggr, sync_aggr))
        return network_perf

    @staticmethod
    def get_validator_duties_outcome(
        validator: LidoValidator,
        duties: ValidatorDuties,
        threshold: float,
        reward_share: float,
        perf_coeffs: PerformanceCoefficients,
        log_operator: OperatorFrameSummary,
    ) -> ValidatorDutiesOutcome:
        if duties.attestation is None or duties.attestation.assigned == 0:
            # It's possible that the validator is not assigned to any duty, hence it's performance
            # is not presented in the aggregates (e.g. exited, pending for activation etc).
            #
            # There is a case when validator is exited and still in sync committee. But we can't count his
            # `participation_share` because there is no `assigned` attestations for him.
            return ValidatorDutiesOutcome(participation_share=0, rebate_share=0, strikes=0)

        log_validator = log_operator.validators[validator.index]

        if validator.validator.slashed:
            # It means that validator was active during the frame and got slashed and didn't meet the exit
            # epoch, so we should not count such validator for operator's share.
            log_validator.slashed = True
            return ValidatorDutiesOutcome(participation_share=0, rebate_share=0, strikes=1)

        performance = perf_coeffs.calc_performance(duties)

        log_validator.threshold = threshold
        log_validator.rewards_share = reward_share
        log_validator.performance = performance
        log_validator.attestation_duty = duties.attestation
        if duties.proposal:
            log_validator.proposal_duty = duties.proposal
        if duties.sync:
            log_validator.sync_duty = duties.sync

        if performance > threshold:
            #
            #  - Count of assigned attestations used as a metrics of time the validator was active in the current frame.
            #  - Reward share is a share of the operator's reward the validator should get, and
            #    it can be less than 1 due to the value from `CSParametersRegistry`.
            #    In case of decimal value, the reward should be rounded up in favour of the operator.
            #
            #    Example:
            #     - Validator was 103 epochs active in the frame (assigned 103 attestations)
            #     - Reward share for this Operator's key is 0.85
            #    87.55 ≈ 88 of 103 participation shares should be counted for the operator key's reward.
            #    The rest 15 participation shares should be counted for the protocol's rebate.
            #
            participation_share = math.ceil(duties.attestation.assigned * reward_share)
            rebate_share = duties.attestation.assigned - participation_share
            if rebate_share < 0:
                raise ValueError(f"Invalid rebate share: {rebate_share=}")
            return ValidatorDutiesOutcome(participation_share, rebate_share, strikes=0)

        # In case of bad performance the validator should be striked and assigned attestations are not counted for
        # the operator's reward and rebate, so rewards will be socialized between CSM operators.
        return ValidatorDutiesOutcome(participation_share=0, rebate_share=0, strikes=1)

    @staticmethod
    def calc_rewards_distribution_in_frame(
        participation_shares: dict[NodeOperatorId, dict[ValidatorIndex, ParticipationShares]],
        rebate_share: ParticipationShares,
        rewards_to_distribute: RewardsShares,
        log: FramePerfLog,
    ) -> dict[NodeOperatorId, RewardsShares]:
        if rewards_to_distribute < 0:
            raise ValueError(f"Invalid rewards to distribute: {rewards_to_distribute=}")

        rewards_distribution: dict[NodeOperatorId, RewardsShares] = defaultdict(RewardsShares)

        node_operators_participation_shares_sum = 0
        per_node_operator_participation_shares: dict[NodeOperatorId, ParticipationShares] = {}
        for no_id, per_validator_participation_shares in participation_shares.items():
            no_participation_share = sum(per_validator_participation_shares.values())
            if no_participation_share == 0:
                # Skip operators with zero participation
                continue
            per_node_operator_participation_shares[no_id] = no_participation_share
            node_operators_participation_shares_sum += no_participation_share

        total_shares = rebate_share + node_operators_participation_shares_sum

        for no_id, no_participation_share in per_node_operator_participation_shares.items():
            rewards_distribution[no_id] = rewards_to_distribute * no_participation_share // total_shares

            # Just for logging purpose. We don't expect here any accurate values.
            for val_index, val_participation_share in participation_shares[no_id].items():
                log.operators[no_id].validators[val_index].distributed_rewards = (
                        rewards_to_distribute * val_participation_share // total_shares
                )

        return rewards_distribution

    @staticmethod
    def validate_distribution(total_distributed_rewards, total_rebate, total_rewards_to_distribute):
        if (total_distributed_rewards + total_rebate) > total_rewards_to_distribute:
            raise ValueError(
                f"Invalid distribution: {total_distributed_rewards} + {total_rebate} > {total_rewards_to_distribute}"
            )

    def _process_strikes(
        self,
        acc: dict[StrikesValidator, StrikesList],
        strikes_in_frame: dict[StrikesValidator, int],
        frame_blockstamp: ReferenceBlockStamp,
    ) -> dict[StrikesValidator, StrikesList]:
        merged = deepcopy(acc)

        for key in strikes_in_frame:
            if key not in merged:
                merged[key] = StrikesList()
            merged[key].push(strikes_in_frame[key])

        for key in list(merged.keys()):
            no_id, _ = key
            if key not in strikes_in_frame:
                merged[key].push(StrikesList.SENTINEL)  # Just shifting...
            maxlen = self.w3.csm.get_curve_params(no_id, frame_blockstamp).strikes_params.lifetime
            merged[key].resize(maxlen)
            # NOTE: Cleanup sequences like [0,0,0] since they don't bring any information.
            if not sum(merged[key]):
                del merged[key]

        return merged
