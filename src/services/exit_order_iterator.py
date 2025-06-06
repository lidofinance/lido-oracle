import logging
from dataclasses import dataclass

from src.constants import TOTAL_BASIS_POINTS
from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.submodules.types import ChainConfig
from src.services.validator_state import LidoValidatorStateService
from src.types import ReferenceBlockStamp, NodeOperatorGlobalIndex, StakingModuleId
from src.utils.validator_state import is_on_exit
from src.web3py.extensions.lido_validators import LidoValidator, StakingModule, NodeOperator, NodeOperatorLimitMode
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


@dataclass
class StakingModuleStats:
    staking_module: StakingModule
    predictable_validators: int = 0


@dataclass
class NodeOperatorStats:
    node_operator: NodeOperator
    module_stats: StakingModuleStats

    predictable_validators: int = 0
    force_exit_to: int | None = None
    soft_exit_to: int | None = None


class ValidatorExitIterator:
    """
    To determine which validators to request for exit, the VEBO selects one entry
    from the sorted list of exitable Lido validators until the demand in WQ is covered by
    the exiting validators and future rewards, or until the limit per report is reached.

    Staking Router v2.0 ejection order.

    | Sorting | Module                                      | Node Operator                                         | Validator              |
    | ------- | ------------------------------------------- | ----------------------------------------------------- | ---------------------- |
    | V       |                                             | Highest number of targeted validators to boosted exit |                        |
    | V       |                                             | Highest number of targeted validators to smooth exit  |                        |
    | V       | Highest deviation from the exit share limit |                                                       |                        |
    | V       |                                             | Highest number of validators                          |                        |
    | V       |                                             |                                                       | Lowest validator index |
    """
    index: int = 0
    total_lido_validators: int = 0
    module_stats: dict[StakingModuleId, StakingModuleStats] = {}
    node_operators_stats: dict[NodeOperatorGlobalIndex, NodeOperatorStats] = {}
    exitable_validators: dict[NodeOperatorGlobalIndex, list[LidoValidator]] = {}

    max_validators_to_exit: int = 0

    def __init__(
        self,
        w3: Web3,
        blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.chain_config = chain_config

        self.lvs = LidoValidatorStateService(self.w3)

        self._reset_attributes()

    def _reset_attributes(self):
        self.module_stats = {}
        self.node_operators_stats = {}
        self.exitable_validators = {}

    @duration_meter()
    def __iter__(self) -> 'ValidatorExitIterator':
        self.index = 0
        self.total_lido_validators = 0
        self._reset_attributes()
        self._prepare_data_structure()
        self._calculate_lido_stats()
        self._load_blockchain_state()
        return self

    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        if self.index == self.max_validators_to_exit:
            raise StopIteration

        for node_operator in sorted(self.node_operators_stats.values(), key=self._no_predicate):
            gid = (
                node_operator.module_stats.staking_module.id,
                node_operator.node_operator.id,
            )
            # Check if there is exitable validators
            # get next node operator if yes
            if not self.exitable_validators[gid]:
                continue

            self.index += 1
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
            self.exitable_validators[gid] = list(filter(self.get_can_request_exit_predicate(gid), validators_list))
            self.exitable_validators[gid].sort(key=lambda val: val.index)

    def _calculate_lido_stats(self):
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(self.blockstamp)

        for gid, validators in self.exitable_validators.items():

            # Calculate validators that are not yet in CL
            deposited_validators = self.node_operators_stats[gid].node_operator.total_deposited_validators
            transient_validators_count = deposited_validators - len(lido_validators[gid])

            no_predictable_validators = len(validators) + transient_validators_count

            self.total_lido_validators += no_predictable_validators
            self.module_stats[gid[0]].predictable_validators += no_predictable_validators
            self.node_operators_stats[gid].predictable_validators = no_predictable_validators

            if self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.FORCE:
                self.node_operators_stats[gid].force_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

            elif self.node_operators_stats[gid].node_operator.is_target_limit_active == NodeOperatorLimitMode.SOFT:
                self.node_operators_stats[gid].soft_exit_to = self.node_operators_stats[gid].node_operator.target_validators_count

    def _load_blockchain_state(self):
        self.max_validators_to_exit = self.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits(
            self.blockstamp.block_hash,
        ).max_validator_exit_requests_per_report

    def get_can_request_exit_predicate(self, gid: NodeOperatorGlobalIndex):
        """Validators that are presented but not yet activated on CL can be requested to exit in advance."""
        indexes = self.lvs.get_recently_requested_to_exit_validators_by_node_operator(self.chain_config.seconds_per_slot, self.blockstamp)

        def is_validator_exitable(validator: LidoValidator):
            """Returns True if validator is exitable: not on exit and not requested to exit"""
            return not is_on_exit(validator) and not validator.index in indexes[gid]

        return is_validator_exitable

    def _eject_validator(self, gid: NodeOperatorGlobalIndex) -> LidoValidator:
        lido_validator = self.exitable_validators[gid].pop(0)

        # Change lido total
        self.total_lido_validators -= 1
        # Change module total
        self.module_stats[gid[0]].predictable_validators -= 1
        # Change node operator stats
        self.node_operators_stats[gid].predictable_validators -= 1

        logger.debug({
            'msg': 'Iterator state change. Eject validator.',
            'total_lido_validators': self.total_lido_validators,
            'no_gid': gid[0],
            'module_stats': self.module_stats[gid[0]].predictable_validators,
            'no_stats_exitable_validators': self.node_operators_stats[gid].predictable_validators,
        })

        return lido_validator

    def _no_predicate(self, node_operator: NodeOperatorStats) -> tuple:
        return (
            - self._no_force_predicate(node_operator),
            - self._no_soft_predicate(node_operator),
            - self._max_share_rate_coefficient_predicate(node_operator),
            - node_operator.predictable_validators,
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

    def _max_share_rate_coefficient_predicate(self, node_operator: NodeOperatorStats) -> int:
        """
        The higher coefficient the higher priority to eject validator
        """
        max_share_rate = node_operator.module_stats.staking_module.priority_exit_share_threshold / TOTAL_BASIS_POINTS

        max_validators_count = int(max_share_rate * self.total_lido_validators)
        return max(node_operator.module_stats.predictable_validators - max_validators_count, 0)

    def _lowest_validator_index_predicate(self, node_operator: NodeOperatorStats) -> int:
        validators = self.exitable_validators[(
            node_operator.node_operator.staking_module.id,
            node_operator.node_operator.id,
        )]

        # If NO doesn't have exitable validators - sorting by validators index doesn't matter
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

        # Extra validators limited by VEBO report
        while self.index < self.max_validators_to_exit:
            for no_stats in sorted(self.node_operators_stats.values(), key=self.no_remaining_forced_predicate):
                if self._no_force_predicate(no_stats) == 0:
                    # The current and all subsequent NOs in the list has no forced validators to exit. Cycle done
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
