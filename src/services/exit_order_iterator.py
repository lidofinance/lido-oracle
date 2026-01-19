import logging
from collections import defaultdict
from dataclasses import dataclass

from eth_typing import HexStr

from src.constants import TOTAL_BASIS_POINTS, EPOCHS_PER_DAY
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.submodules.types import ChainConfig, FrameConfig
from src.providers.keys.types import LidoKey
from src.services.validator_state import LidoValidatorStateService
from src.types import ReferenceBlockStamp, NodeOperatorGlobalIndex, StakingModuleId, Gwei
from src.utils.validator_state import is_on_exit, get_max_effective_balance
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    StakingModule,
    NodeOperator,
    NodeOperatorLimitMode,
)
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    predictable_balance: Gwei = 0


@dataclass
class NodeOperatorStats:
    node_operator: NodeOperator
    module_stats: StakingModuleStats

    predictable_validators: int = 0
    predictable_balance: Gwei = 0

    weight: float = 1

    force_exit_to: int | None = None
    soft_exit_to: int | None = None


def get_validator_balance_by_index(lido_validators, source_index):
    for validators in lido_validators.values():
        for validator in validators:
            if validator.index == source_index:
                return validator.balance

    # If validator not found it is probably non-lido one. We can ignore it to optimize search
    return 0


def get_effective_balance(validator: LidoValidator, incoming_balance: Gwei = Gwei(0)) -> Gwei:
    return min(
        get_max_effective_balance(validator.validator),
        Gwei(validator.balance + incoming_balance),
    )


class ValidatorExitIterator:
    """
    To determine which validators to request for exit, the VEBO selects one entry
    from the sorted list of exitable Lido validators until the demand in WQ is covered by
    the exiting validators and future rewards, or until the limit per report is reached.

    Staking Router v2.0 ejection order.

    | Sorting | Staking Module                                                        | Node Operator                                         | Validator              |
    | ------- | --------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------- |
    | V       |                                                                       | Highest number of targeted validators to boosted exit |                        |
    | V       |                                                                       | Highest number of targeted validators to smooth exit  |                        |
    | V       | Highest deviation from the exit share limit or the biggest by balance |                                                       |                        |
    | V       |                                                                       | Highest rate weight to effective balance              |                        |
    | V       |                                                                       |                                                       | Lowest validator index |
    """
    def __init__(
        self,
        w3: Web3,
        blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
        frame_config: FrameConfig,
    ):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.chain_config = chain_config
        self.frame_config = frame_config
        self.lvs = LidoValidatorStateService(self.w3)

    # --- Iterator initialization ---
    @duration_meter()
    def __iter__(self) -> 'ValidatorExitIterator':
        self.index = 0
        # Sum of all max effective balances for validators going to exit. Required to make sure we pass a sanity check.
        self._max_exit_balance = 0

        self._reset_iterator_data()
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._get_report_limits()
        return self

    def _reset_iterator_data(self):
        self.total_lido_predictable_balance = 0
        self.module_stats: dict[StakingModuleId, StakingModuleStats] = {}
        self.node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
        self.exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

    def _prepare_data_structure(self):
        modules = self.w3.lido_contracts.staking_router.get_staking_modules(self.blockstamp.block_hash)
        for module in modules:
            self.module_stats[module.id] = StakingModuleStats(module)

        node_operators = self.w3.lido_validators.get_lido_node_operators(self.blockstamp)
        for node_operator in node_operators:
            self.node_operators_stats[(node_operator.staking_module.id, node_operator.id)] = NodeOperatorStats(
                node_operator,
                self.module_stats[node_operator.staking_module.id],
            )

        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        for gid, validators_list in lido_validators.items():
            self.exitable_validators[gid] = list(filter(self.get_can_request_exit_predicate(gid), validators_list))
            self.exitable_validators[gid].sort(key=lambda val: val.index)

    def _calculate_lido_stats(self):
        # Calculate current stats on CL
        self._calculate_lido_cl_stats()
        # Calculate all new validators coming, but not yet on CL
        self._calculate_lido_predictable_stats()

    def _calculate_lido_cl_stats(self):
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        state = self.w3.cc.get_state_view(self.blockstamp)

        # get all pending deposits
        pending_deposits_by_pubkey = defaultdict(list)
        for deposit in state.pending_deposits:
            pending_deposits_by_pubkey[deposit.pubkey].append(deposit)

        # Get all consolidations
        pending_consolidations_by_target_index = defaultdict(list)
        for consolidation in state.pending_consolidations:
            pending_consolidations_by_target_index[consolidation.target_index].append(consolidation)

        for gid, validators in self.exitable_validators.items():
            self.node_operators_stats[gid].predictable_validators += len(validators)

            if self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.FORCE:
                self.node_operators_stats[gid].force_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

            elif self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.SOFT:
                self.node_operators_stats[gid].soft_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

            # Calculate predictable effective balance by each NO
            for v in validators:
                # --- Calculate predictable effective balance ---
                validator_pending_deposits_balance = sum(pd.amount for pd in pending_deposits_by_pubkey[v.pubkey])
                # No double accounting of consolidations because each source validator can only have one valid consolidation request
                # Revise this if consolidations are allowed to be sent to multiple targets
                validator_pending_consolidations_balance = sum(get_validator_balance_by_index(lido_validators, pc.source_index) for pc in pending_consolidations_by_target_index[v.index])

                incoming_balance = Gwei(validator_pending_deposits_balance + validator_pending_consolidations_balance)
                validator_predictable_balance = get_effective_balance(v, incoming_balance)

                # --- Update lido stats ---
                self.total_lido_predictable_balance += validator_predictable_balance
                self.module_stats[gid[0]].predictable_balance += validator_predictable_balance
                self.node_operators_stats[gid].predictable_balance += validator_predictable_balance

    def _calculate_lido_predictable_stats(self):
        pending_deposits = self.w3.cc.get_state_view(self.blockstamp).pending_deposits

        lido_keys: dict[HexStr, LidoKey] = {key.key: key for key in self.w3.kac.get_used_lido_keys(self.blockstamp)}
        validator_pubkeys: list[HexStr] = [v.validator.pubkey for v in self.w3.cc.get_validators(self.blockstamp)]
        staking_modules = {
            sm.address: sm.id
            for sm in self.w3.lido_contracts.staking_router.get_staking_modules(self.blockstamp)
        }

        for deposit in pending_deposits:
            if deposit.pubkey not in lido_keys:
                continue

            if deposit.pubkey in validator_pubkeys:
                continue

            lido_key = lido_keys[deposit.pubkey]

            gid = (staking_modules[lido_key.moduleAddress].id, lido_key.operatorIndex)

            # Deposit to non-exiting yet Lido validator
            self.total_lido_predictable_balance += deposit.amount
            self.module_stats[gid[0]].predictable_balance += deposit.amount
            self.node_operators_stats[gid].predictable_balance += deposit.amount

    def _get_report_limits(self):
        exit_limit_per_day = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(self.blockstamp.block_hash).exit_balance_per_day_limit

        self.max_balance_limit_per_frame = exit_limit_per_day / EPOCHS_PER_DAY * self.frame_config.epochs_per_frame

    # --- Iterator ---
    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            # Check if there are exitable validators
            # get the next node operator if yes
            if not self.exitable_validators[gid]:
                continue

            v: LidoValidator = self._eject_validator(gid)
            self._max_exit_balance += get_max_effective_balance(v.validator)

            if self._max_exit_balance > self.max_balance_limit_per_frame:
                raise StopIteration

            return gid, v

        raise StopIteration

    def get_can_request_exit_predicate(self, gid: NodeOperatorGlobalIndex):
        """
        Validators that are presented but not yet activated on CL can be requested to exit in advance.

        There is an edge case when a validator's consolidation request is still in the queue to be processed.
        Theoretically, we can check it and verify if it is valid. If it is valid, the validator won't be excitable soon,
        but the check is very complex and requires more additional data and some prediction to make. Decided to skip it.
        """
        indexes = self.lvs.get_recently_requested_to_exit_validators_by_node_operator(self.chain_config.seconds_per_slot, self.blockstamp)

        def is_validator_exitable(validator: LidoValidator):
            """Returns True if the validator is exitable: not on exit and not requested to exit"""
            return not is_on_exit(validator) and validator.index not in indexes[gid]

        return is_validator_exitable

    def _eject_validator(self, gid: NodeOperatorGlobalIndex) -> LidoValidator:
        lido_validator = self.exitable_validators[gid].pop(0)

        exit_balance = get_effective_balance(lido_validator)

        # Change lido total
        self.total_lido_predictable_balance -= exit_balance
        # Change module total
        self.module_stats[gid[0]].predictable_balance -= exit_balance
        # Change node operator stats
        self.node_operators_stats[gid].predictable_validators -= 1
        self.node_operators_stats[gid].predictable_balance -= exit_balance

        logger.debug({
            'msg': 'Iterator state change. Eject validator.',
            'total_lido_predictable_balance': self.total_lido_predictable_balance,
            'no_gid': gid[0],
            'module_stats': self.module_stats[gid[0]].predictable_balance,
            'no_stats_exitable_validators': self.node_operators_stats[gid].predictable_balance,
        })

        return lido_validator

    def _no_predicate(self, node_operator: NodeOperatorStats) -> tuple:
        return (
            - self._no_force_predicate(node_operator),
            - self._no_soft_predicate(node_operator),
            - self._max_share_rate_coefficient_predicate(node_operator),
            self._no_weight_predicate(node_operator),
            self._lowest_validator_index_predicate(node_operator),
        )

    @staticmethod
    def _no_force_predicate(node_operator: NodeOperatorStats) -> int:
        return ValidatorExitIterator._get_expected_validators_diff(
            node_operator.predictable_validators,
            node_operator.force_exit_to,
        )

    @staticmethod
    def _no_soft_predicate(node_operator: NodeOperatorStats) -> int:
        return ValidatorExitIterator._get_expected_validators_diff(
            node_operator.predictable_validators,
            node_operator.soft_exit_to,
        )

    @staticmethod
    def _get_expected_validators_diff(current: int, expected: int | None):
        if expected is not None:
            if current > expected:
                return current - expected
        return 0

    def _max_share_rate_coefficient_predicate(self, node_operator: NodeOperatorStats) -> float:
        """
        The higher coefficient the higher priority to eject validator
        """
        max_share_rate = node_operator.module_stats.staking_module.priority_exit_share_threshold / TOTAL_BASIS_POINTS

        max_module_predictable_balance = int(max_share_rate * self.total_lido_predictable_balance)

        if node_operator.module_stats.predictable_balance > max_module_predictable_balance:
            return node_operator.module_stats.predictable_balance - max_module_predictable_balance

        return - 1 / node_operator.module_stats.predictable_balance

    def _no_weight_predicate(self, node_operator: NodeOperatorStats) -> float:
        if node_operator.predictable_balance == 0:
            return 0

        return node_operator.weight / node_operator.predictable_balance

    def _lowest_validator_index_predicate(self, node_operator: NodeOperatorStats) -> int:
        validators = self.exitable_validators[(
            node_operator.node_operator.staking_module.id,
            node_operator.node_operator.id,
        )]

        # If NO doesn't have exitable validators - sorting by validator index doesn't matter
        first_val_index = 0
        if validators:
            first_val_index = validators[0].index

        return first_val_index

    def get_remaining_forced_validators(self) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        """
        Returns a list of validators from NOs that are requested for forced exit.
        This includes an additional scenario where enough validators have been ejected to fulfill the withdrawal requests,
        but forced ejections are still necessary.
        """
        result: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []

        # Extra validators limited by a VEBO report
        while self.index < self.report_size:
            for no_stats in sorted(self.node_operators_stats.values(), key=self.no_remaining_forced_predicate):
                if self._no_force_predicate(no_stats) == 0:
                    # The current and all further NOs in the list have no forced validators to exit. Cycle done
                    return result

                gid = (
                    no_stats.node_operator.staking_module.id,
                    no_stats.node_operator.id,
                )

                if self.exitable_validators[gid]:
                    # When found Node Operator
                    self.index += 1
                    result.append((gid, self._eject_validator(gid)))
                    break
            else:
                break

        return result

    def no_remaining_forced_predicate(self, no: NodeOperatorStats) -> tuple:
        return (
            -self._no_force_predicate(no),
            self._lowest_validator_index_predicate(no),
        )
