from dataclasses import dataclass
from typing import Iterator, Optional

from more_itertools import ilen

from src.constants import TOTAL_BASIS_POINTS
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.submodules.types import ChainConfig
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
    total_lido_validators = 0
    module_stats: dict[StakingModuleId, StakingModuleStats] = {}
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
    lido_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

    _done: bool = True

    def __init__(self, w3: Web3, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.chain_config = chain_config

    @duration_meter()
    def __iter__(self) -> Iterator[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        self._done = False
        self.index = 0
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._load_constants()
        return self

    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        if self.index >= self.max_validators_to_exit:
            raise StopIteration

        node_operator = sorted(self.node_operators_stats.values(), key=self._no_predicate)[0]

        if not node_operator.exitable_validators:
            raise StopIteration

        self.index += 1

        gid = NodeOperatorGlobalIndex(node_operator.module_stats.staking_module.id, node_operator.node_operator.id)
        return gid, self._eject_validator(gid)

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
            self.lido_validators[gid] = list(filter(self.get_filter_non_exitable_validators(gid), validators_list))
            self.lido_validators[gid].sort(key=lambda val: val.index)

    def _calculate_lido_stats(self):
        delayed_validators = self._get_delayed_validators()

        for gid, validators in self.lido_validators.items():
            self.total_lido_validators += len(validators)

            self.module_stats[gid[0]].exitable_validators += len(validators)
            self.node_operators_stats[gid].exitable_validators = len(validators)

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

    def get_filter_non_exitable_validators(self, gid: NodeOperatorGlobalIndex):
        """
        If validator was deposited, but isn't representended on CL side он считается exitable
        """
        indexes = self.w3.lido_validators.get_operators_with_last_exited_validator_indexes(self.blockstamp)

        def is_validator_exitable(validator: LidoValidator):
            """Returns True if validator is exitable: not on exit and not requested to exit"""
            requested_to_exit = int(validator.index) <= indexes[gid]
            return not is_on_exit(validator) and not requested_to_exit

        return is_validator_exitable

    def _get_delayed_validators(self) -> dict[NodeOperatorGlobalIndex, int]:
        last_requested_to_exit = self.w3.lido_validators.get_operators_with_last_exited_validator_indexes(self.blockstamp)

        validators_timeout = self.w3.lido_contracts.oracle_daemon_config.validator_delayed_timeout_in_slots(
            self.blockstamp.block_hash,
        )
        recent_requests = self.w3.lido_validators.get_recently_requests_to_exit_indexes_by_operators(
            self.chain_config.seconds_per_slot,
            validators_timeout,
            self.blockstamp,
        )

        result = {}

        for gid, validators_list in self.lido_validators.items():

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
        validator = self.lido_validators[gid].pop(0)

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
            self._no_force_predicate(node_operator),
            self._no_soft_predicate(node_operator),
            self._max_share_rate_coefficient(node_operator),
            self._stake_weight_coefficient(node_operator),
            - node_operator.exitable_validators
        )

    def _max_share_rate_coefficient(self, node_operator: NodeOperatorStats) -> int:
        """
        The lower coefficient the higher priority to eject validator
        """
        max_share_rate = node_operator.module_stats.staking_module.priority_exit_share_threshold / TOTAL_BASIS_POINTS
        max_validators_count = int(max_share_rate * self.total_lido_validators)
        return max(max_validators_count - node_operator.module_stats.exitable_validators, 0)

    def _stake_weight_coefficient(self, node_operator: NodeOperatorStats) -> int:
        """
        The lower coefficient the higher priority to eject validator
        """
        no_penetration = self.w3.lido_contracts.oracle_daemon_config.node_operator_network_penetration_threshold_bp(
            block_identifier=self.blockstamp.block_hash,
        ) / TOTAL_BASIS_POINTS

        eth_validators_count = ilen(v for v in self.w3.cc.get_validators(self.blockstamp) if not is_on_exit(v))

        if eth_validators_count * no_penetration < node_operator.exitable_validators:
            return -node_operator.total_age

        return 0

    def get_remaining_forced_validators(self) -> list[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        if self._done:
            raise RuntimeError('Cant call method `get_remaining_forced_validators` before iterator.')

        self._done = True

        result = []
        for i in range(self.max_validators_to_exit - self.index):
            node_operator = sorted(self.node_operators_stats.values(), key=self._no_force_predicate)[0]

            if self._no_force_predicate(node_operator) == 0:
                break

            gid = NodeOperatorGlobalIndex(node_operator.module_stats.staking_module.id, node_operator.node_operator.id)
            result.append((gid, self._eject_validator(gid)))

        return result

    @staticmethod
    def _no_force_predicate(node_operator: NodeOperatorStats) -> int:
        return node_operator.force_exit_to - node_operator.exitable_validators if node_operator.force_exit_to else 0

    @staticmethod
    def _no_soft_predicate(node_operator: NodeOperatorStats) -> int:
        return node_operator.soft_exit_to - node_operator.exitable_validators if node_operator.soft_exit_to else 0
