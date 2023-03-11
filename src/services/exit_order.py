from typing import Iterator

from eth_typing import HexStr
from eth_typing import ChecksumAddress

from src.modules.submodules.typings import ChainConfig
from src.services.exit_order_state import ExitOrderStateService, NodeOperatorPredictableState
from src.typings import ReferenceBlockStamp

from src.utils.validator_state import get_validator_age
from src.web3py.extensions.lido_validators import (
    LidoValidator,
    NodeOperatorGlobalIndex,
    NodeOperatorId,
    StakingModuleId,
)
from src.web3py.typings import Web3


class ExitOrderIterator:
    """
    Exit order predicates sequence:
    1. Validator whose operator with the lowest number of delayed validators
    2. Validator whose operator with the highest number of targeted validators to exit
    3. Validator whose operator with the highest stake weight
    4. Validator whose operator with the highest number of predictable to exit validators
    5. Validator with the lowest index
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

    def __iter__(self) -> Iterator[tuple[NodeOperatorGlobalIndex, LidoValidator]]:
        """
        Prepare queue state for the iteration:.
        Determine exitable Lido validators and collect operators stats to sort exitable validators
        """
        eos = ExitOrderStateService(self.w3, self.blockstamp)

        self.left_queue_count = 0
        self.max_validators_to_exit = eos.get_oracle_report_limits(self.blockstamp).max_validator_exit_requests_per_report
        self.operator_network_penetration_threshold = eos.get_operator_network_penetration_threshold(self.blockstamp)

        # Prepare list of exitable validators, which will be sorted by exit order predicates
        self.exitable_lido_validators = eos.get_exitable_lido_validators()
        # Prepare dict of node operators stats to sort exitable validators
        self.lido_node_operator_stats = eos.prepare_lido_node_operator_stats(self.blockstamp, self.chain_config)
        # And total predictable validators count to stake weight sort predicate
        self.total_predictable_validators_count = eos.get_total_predictable_validators_count(
            self.blockstamp,
            self.lido_node_operator_stats
        )

        # Prepare dict of staking module id by staking module address for faster search
        self.staking_module_id = {
            operator.staking_module.staking_module_address: operator.staking_module.id
            for operator in self.w3.lido_validators.get_lido_node_operators(self.blockstamp)
        }
        return self

    def __next__(self) -> tuple[NodeOperatorGlobalIndex, LidoValidator]:
        if self.left_queue_count >= self.max_validators_to_exit:
            raise StopIteration

        if not self.exitable_lido_validators:
            raise StopIteration

        self.exitable_lido_validators.sort(key=self._predicates)
        to_exit = self.exitable_lido_validators.pop(0)
        self._decrease_node_operator_stats(to_exit)
        self.left_queue_count += 1
        global_index = ExitOrderIterator.operator_index_by_validator(self.staking_module_id, to_exit)
        return global_index, to_exit

    def _decrease_node_operator_stats(self, validator: LidoValidator) -> None:
        """
        Sub particular validator stats from its node operator stats
        We do it every time when validator is popped from the queue for resort the rest of queue
        """
        module_operator = ExitOrderIterator.operator_index_by_validator(self.staking_module_id, validator)
        self.total_predictable_validators_count -= 1
        self.lido_node_operator_stats[module_operator].predictable_validators_count -= 1
        self.lido_node_operator_stats[module_operator].predictable_validators_total_age -= get_validator_age(
            validator, self.blockstamp.ref_epoch
        )

    # -- Predicates for sorting validators --
    def _predicates(self, validator: LidoValidator) -> tuple:
        module_operator = ExitOrderIterator.operator_index_by_validator(self.staking_module_id, validator)
        operator_stats = self.lido_node_operator_stats[module_operator]
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
        if operator_state.targeted_validators_limit_is_enabled:
            return max(0, operator_state.predictable_validators_count - operator_state.targeted_validators_limit_count)
        return 0

    @staticmethod
    def _operator_stake_weight(
        operator_state: NodeOperatorPredictableState,
        total_predictable_validators_count: int,
        operator_network_penetration_threshold: float
    ) -> int:
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
