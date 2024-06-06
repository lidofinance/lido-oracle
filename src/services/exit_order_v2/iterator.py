from dataclasses import dataclass
from typing import Iterator, Optional

from more_itertools import ilen

from src.constants import TOTAL_BASIS_POINTS
from src.metrics.prometheus.duration_meter import duration_meter
from src.services.validator_state import LidoValidatorStateService
from src.types import ReferenceBlockStamp, NodeOperatorGlobalIndex, StakingModuleId
from src.utils.validator_state import is_on_exit, get_validator_age
from src.web3py.extensions.lido_validators import LidoValidator, StakingModule, NodeOperator, NodeOperatorLimitMode
from src.web3py.types import Web3


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    exitable_validators: int = 0


@dataclass
class NodeOperatorStats:
    node_operator: NodeOperator
    module_stats: StakingModuleStats

    exitable_validators: int = 0
    delayed_validators: int = 0
    total_age: int = 0
    force_exit_to: Optional[int] = None
    soft_exit_to: Optional[int] = None


class ValidatorExitIteratorV2:
    """
    To determine which validators to request for exit, the VEBO selects one entry
    from the sorted list of exitable Lido validators until the demand in WQ is covered by
    the exiting validators and future rewards, or until the limit per report is reached.

    Staking Router 1.5 ejection order.

    | Sorting | Module                                      | Node Operator                                         | Validator              |
    | ------- | ------------------------------------------- | ----------------------------------------------------- | ---------------------- |
    | V       |                                             | Lowest number of delayed validators                   |                        |
    | V       |                                             | Highest number of targeted validators to boosted exit |                        |
    | V       |                                             | Highest number of targeted validators to smooth exit  |                        |
    | V       | Highest deviation from the exit share limit |                                                       |                        |
    | V       |                                             | Highest stake weight                                  |                        |
    | V       |                                             | Highest number of validators                          |                        |
    | V       |                                             |                                                       | Lowest validator index |
    """
    index: int = 0
    total_lido_validators: int = 0
    module_stats: dict[StakingModuleId, StakingModuleStats] = {}
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
    exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

    max_validators_to_exit: int

    no_penetration: int = -1
    eth_validators_count: int = -1

    def __init__(self, w3: Web3, blockstamp: ReferenceBlockStamp, seconds_per_slot: int):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.seconds_per_slot = seconds_per_slot

        self.lvs = LidoValidatorStateService(self.w3)

    @duration_meter()
    def __iter__(self) -> Iterator[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        self.index = 0
        self.total_lido_validators = 0
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._load_constants()
        return self

    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        if self.index == self.max_validators_to_exit:
            raise StopIteration

        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            if not node_operator.exitable_validators:
                break

            self.index += 1
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            return gid, self._eject_validator(gid)

        raise StopIteration

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
            self.exitable_validators[gid] = list(filter(self.get_filter_non_exitable_validators(gid), validators_list))
            self.exitable_validators[gid].sort(key=lambda val: val.index)

    def _calculate_lido_stats(self):
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)
        delayed_validators = self._get_delayed_validators()

        for gid, validators in self.exitable_validators.items():
            self.total_lido_validators += len(validators)

            # Calculate validators that are not yet in CL
            deposited_validators = self.node_operators_stats[gid].node_operator.total_deposited_validators
            transient_validators_count = deposited_validators - len(lido_validators[gid])

            self.module_stats[gid[0]].exitable_validators += len(validators) + transient_validators_count

            self.node_operators_stats[gid].exitable_validators = len(validators) + transient_validators_count
            self.node_operators_stats[gid].delayed_validators = delayed_validators[gid]
            self.node_operators_stats[gid].total_age = self.calculate_validators_age(validators)

            if self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.FORCE:
                self.node_operators_stats[gid].force_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

            elif self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.SOFT:
                self.node_operators_stats[gid].soft_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

    def _load_constants(self):
        self.max_validators_to_exit = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(
            self.blockstamp.block_hash,
        ).max_validator_exit_requests_per_report

        self.no_penetration = self.w3.lido_contracts.oracle_daemon_config.node_operator_network_penetration_threshold_bp(
            block_identifier=self.blockstamp.block_hash,
        ) / TOTAL_BASIS_POINTS

        self.eth_validators_count = ilen(v for v in self.w3.cc.get_validators(self.blockstamp) if not is_on_exit(v))

    def get_filter_non_exitable_validators(self, gid: NodeOperatorGlobalIndex):
        """Validators that were deposited, but not yet represented on CL side are exitable."""
        indexes = self.lvs.get_operators_with_last_exited_validator_indexes(self.blockstamp)

        def is_validator_exitable(validator: LidoValidator):
            """Returns True if validator is exitable: not on exit and not requested to exit"""
            requested_to_exit = int(validator.index) <= indexes[gid]
            return not is_on_exit(validator) and not requested_to_exit

        return is_validator_exitable

    def _get_delayed_validators(self) -> dict[NodeOperatorGlobalIndex, int]:
        last_requested_to_exit = self.lvs.get_operators_with_last_exited_validator_indexes(self.blockstamp)

        recent_requests = self.lvs.get_recently_requested_validators_by_operator(
            self.seconds_per_slot,
            self.blockstamp,
        )

        result = {}

        for gid, validators_list in self.exitable_validators.items():

            def is_delayed(validator: LidoValidator) -> bool:
                requested_to_exit = int(validator.index) <= last_requested_to_exit[gid]
                recently_requested_to_exit = int(validator.index) in recent_requests[gid]
                return requested_to_exit and not recently_requested_to_exit and not is_on_exit(validator)

            result[gid] = ilen(val for val in validators_list if is_delayed(val))

        return result

    def calculate_validators_age(self, validators: list[LidoValidator]) -> int:
        result = 0

        for validator in validators:
            result += get_validator_age(validator, self.blockstamp.ref_epoch)

        return result

    def _eject_validator(self, gid: NodeOperatorGlobalIndex) -> LidoValidator:
        validator = self.exitable_validators[gid].pop(0)

        # Change lido total
        self.total_lido_validators -= 1
        # Change module total
        self.module_stats[gid[0]].exitable_validators -= 1
        # Change node operator stats
        self.node_operators_stats[gid].exitable_validators -= 1
        self.node_operators_stats[gid].total_age -= get_validator_age(validator, self.blockstamp.ref_epoch)

        return validator

    def _no_predicate(self, node_operator: NodeOperatorStats) -> tuple:
        return (
            node_operator.delayed_validators,
            - self._no_force_predicate(node_operator),
            - self._no_soft_predicate(node_operator),
            - self._max_share_rate_coefficient_predicate(node_operator),
            - self._stake_weight_coefficient_predicate(
                node_operator,
                self.no_penetration,
                self.eth_validators_count,
            ),
            - node_operator.exitable_validators
        )

    @staticmethod
    def _no_force_predicate(node_operator: NodeOperatorStats) -> int:
        return ValidatorExitIteratorV2._get_expected_validators_diff(
            node_operator.exitable_validators,
            node_operator.force_exit_to,
        )

    @staticmethod
    def _no_soft_predicate(node_operator: NodeOperatorStats) -> int:
        return ValidatorExitIteratorV2._get_expected_validators_diff(
            node_operator.exitable_validators,
            node_operator.soft_exit_to,
        )

    @staticmethod
    def _get_expected_validators_diff(current: int, expected: Optional[int]):
        if expected is not None:
            if current > expected:
                return current - expected
        return 0

    def _max_share_rate_coefficient_predicate(self, node_operator: NodeOperatorStats) -> int:
        """
        The lower coefficient the higher priority to eject validator
        """
        priority_exit_share_threshold = node_operator.module_stats.staking_module.priority_exit_share_threshold

        # ToDo: remove after upgrade to sr v2
        priority_exit_share_threshold = priority_exit_share_threshold if priority_exit_share_threshold is not None else 0

        max_share_rate = priority_exit_share_threshold / TOTAL_BASIS_POINTS

        max_validators_count = int(max_share_rate * self.total_lido_validators)
        return max(node_operator.module_stats.exitable_validators - max_validators_count, 0)

    @staticmethod
    def _stake_weight_coefficient_predicate(
        node_operator: NodeOperatorStats,
        total_validators: int,
        no_penetration: float,
    ) -> int:
        """
        The lower coefficient the higher priority to eject validator
        """
        if total_validators * no_penetration < node_operator.exitable_validators:
            return node_operator.total_age

        return 0

    def get_remaining_forced_validators(self) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        result: list[tuple[NodeOperatorGlobalIndex, LidoValidator]] = []

        while self.index != self.max_validators_to_exit:
            for node_operator in sorted(self.node_operators_stats.values(), key=lambda no: -self._no_force_predicate(no)):
                if self._no_force_predicate(node_operator) == 0:
                    return result

                if node_operator.exitable_validators:
                    self.index += 1
                    gid = (
                        node_operator.module_stats.staking_module.id,
                        node_operator.node_operator.id,
                    )
                    result.append((gid, self._eject_validator(gid)))
                    break

        return result
