import dataclasses
import logging
from typing import Iterator

from eth_typing import ChecksumAddress

from src.metrics.prometheus.duration_meter import duration_meter
from src.modules.submodules.typings import ChainConfig
from src.services.exit_order_iterator_state import ExitOrderIteratorStateService, NodeOperatorPredictableState
from src.typings import ReferenceBlockStamp

from src.utils.validator_state import get_validator_age
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    NodeOperatorGlobalIndex,
    NodeOperatorId,
    StakingModuleId,
)
from src.web3py.typings import Web3

logger = logging.getLogger(__name__)


class ExitOrderIterator:
    """
    Service which gives validators to eject in order of exit priority, but not more than `max_validators_to_exit`.
    Balance of ejected validators will be used to finalize withdrawal requests.

    Exit priority is determined by the sorting predicates in the following order:
       V
       | Validator whose operator with the lowest number of delayed validators
       | Validator whose operator with the highest number of targeted validators to exit
       | Validator whose operator with the highest stake weight
       | Validator whose operator with the highest number of predictable validators
       | Validator with the lowest index
       V

    """
    left_queue_count: int
    max_validators_to_exit: int
    exitable_lido_validators: list[LidoValidator]
    lido_node_operator_stats: dict[NodeOperatorGlobalIndex, NodeOperatorPredictableState]
    total_predictable_validators_count: int

    staking_module_id: dict[ChecksumAddress, StakingModuleId]
    operator_network_penetration_threshold: float

    def __init__(self, web3: Web3, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig):
        self.w3 = web3
        self.blockstamp = blockstamp
        self.chain_config = chain_config

    @duration_meter()
    def __iter__(self) -> Iterator[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        """
        Prepare state of queue for the iteration: form a queue with Lido exitable validators
        and collect operators stats that will be used to sort validators queue
        """
        eois = ExitOrderIteratorStateService(self.w3, self.blockstamp)

        self.left_queue_count = 0
        self.max_validators_to_exit = eois.get_oracle_report_limits(self.blockstamp).max_validator_exit_requests_per_report
        self.operator_network_penetration_threshold = eois.get_operator_network_penetration_threshold(self.blockstamp)

        # Prepare list of exitable validators, which will be sorted by exit order predicates
        self.exitable_lido_validators = eois.get_exitable_lido_validators()
        # Prepare dict of node operators stats to sort exitable validators
        self.lido_node_operator_stats = eois.prepare_lido_node_operator_stats(self.blockstamp, self.chain_config)
        # And total predictable validators count to stake weight sort predicate
        self.total_predictable_validators_count = eois.get_total_predictable_validators_count(
            self.blockstamp,
            self.lido_node_operator_stats
        )

        # Prepare dict of staking module id by staking module address for faster search
        self.staking_module_id = {
            operator.staking_module.staking_module_address: operator.staking_module.id
            for operator in self.w3.lido_validators.get_lido_node_operators(self.blockstamp)
        }
        return self

    @duration_meter()
    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        """
        Sort the queue, pop validator from the queue, decrease particular operator stats and return validator from order
        """
        if self.left_queue_count >= self.max_validators_to_exit:
            raise StopIteration

        if not self.exitable_lido_validators:
            raise StopIteration

        self.exitable_lido_validators.sort(key=self._predicates)
        to_exit = self.exitable_lido_validators.pop(0)
        global_index = self._decrease_node_operator_stats(to_exit)
        self.left_queue_count += 1
        return global_index, to_exit

    def _decrease_node_operator_stats(self, validator: LidoValidator) -> NodeOperatorGlobalIndex:
        """
        Sub particular validator stats from its node operator stats
        We do it every time when validator is popped from the queue for resort the rest of queue
        """
        global_index = ExitOrderIterator.operator_index_by_validator(self.staking_module_id, validator)
        self.total_predictable_validators_count -= 1
        before = NodeOperatorPredictableState(**dataclasses.asdict(self.lido_node_operator_stats[global_index]))
        self.lido_node_operator_stats[global_index].predictable_validators_count -= 1
        self.lido_node_operator_stats[global_index].predictable_validators_total_age -= get_validator_age(
            validator, self.blockstamp.ref_epoch
        )
        logger.debug(
            {
                'msg': f'Operator [{global_index}] stats before and after eject validator [{validator.index}]',
                'before': before,
                'after': self.lido_node_operator_stats[global_index],
            }
        )
        return global_index

    # -- Predicates for sorting validators --
    def _predicates(self, validator: LidoValidator) -> tuple:
        global_index = ExitOrderIterator.operator_index_by_validator(self.staking_module_id, validator)
        operator_stats = self.lido_node_operator_stats[global_index]
        return (
            # positive mean asc sorting
            # negative mean desc sorting
            self._operator_delayed_validators(operator_stats),
            -self._operator_targeted_validators_to_exit(operator_stats),
            -self._operator_stake_weight(
                operator_stats, self.total_predictable_validators_count, self.operator_network_penetration_threshold
            ),
            -self._operator_predictable_validators(operator_stats),
            self._validator_index(validator),
        )

    @staticmethod
    def _operator_delayed_validators(operator_state: NodeOperatorPredictableState) -> int:
        return operator_state.delayed_validators_count

    @staticmethod
    def _operator_targeted_validators_to_exit(operator_state: NodeOperatorPredictableState) -> int:
        """
        If target limit is higher than predictable operator's validators -
        it should not have any influence on sorting order
        """
        if operator_state.targeted_validators_limit_is_enabled:
            return max(0, operator_state.predictable_validators_count - operator_state.targeted_validators_limit_count)
        return 0

    @staticmethod
    def _operator_stake_weight(
        operator_state: NodeOperatorPredictableState,
        total_predictable_validators_count: int,
        operator_network_penetration_threshold: float
    ) -> int:
        """
        We prefer to exit validators which operators with high stake weight first.
        Operators who have stake weight less than `operator_network_penetration_threshold` will have the same weight
        """
        stake_volume = operator_state.predictable_validators_count / total_predictable_validators_count
        if stake_volume > operator_network_penetration_threshold:
            return operator_state.predictable_validators_total_age
        return 0

    @staticmethod
    def _operator_predictable_validators(operator_state: NodeOperatorPredictableState) -> int:
        return operator_state.predictable_validators_count

    @staticmethod
    def _validator_index(validator: LidoValidator) -> int:
        return int(validator.index)

    @staticmethod
    def operator_index_by_validator(
        staking_module_id: dict[ChecksumAddress, StakingModuleId], validator: LidoValidator
    ) -> NodeOperatorGlobalIndex:
        return (
            StakingModuleId(staking_module_id[validator.lido_id.moduleAddress]),
            NodeOperatorId(validator.lido_id.operatorIndex),
        )
