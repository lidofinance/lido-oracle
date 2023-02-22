from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from eth_typing import Address
from web3.types import EventData

from src.constants import FAR_FUTURE_EPOCH
from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator

from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import LidoValidator, NodeOperator, NodeOperatorIndex, StakingModuleId, \
    NodeOperatorId
from src.web3py.typings import Web3


@dataclass
class NodeOperatorPredictableState:
    predictable_validators_total_age: int
    predictable_validators_count: int
    targeted_validators: int | None
    delayed_validators: int


class ValidatorsExit:
    """
    Exit order predicates sequence:
    1. Validator whose operator with the lowest number of delayed validators
    2. Validator whose operator with the highest number of targeted validators to exit
    3. Validator whose operator with the highest stake weight
    4. Validator whose operator with the highest number of validators
    5. Validator with the lowest activation epoch
    6. Validator with the lowest index
    """
    staking_module_id: dict[Address, StakingModuleId]
    lido_node_operator_stats: dict[NodeOperatorIndex, NodeOperatorPredictableState]
    total_predictable_validators_count: int

    def __init__(
        self,
        w3: Web3,
        blockstamp: BlockStamp,
        c_conf: ChainConfig,
        exitable_lido_validators: list[LidoValidator],
        max_validators_to_exit: int,
    ):
        self.w3 = w3
        self.blockstamp = blockstamp
        self.c_conf = c_conf
        self.exitable_lido_validators = exitable_lido_validators
        self.max_validators_to_exit = max_validators_to_exit
        self.left_queue_count = 0

        # -- State init part --

        self.validator_delayed_timeout_in_slots = Web3.to_int(
            self.w3.lido_contracts.oracle_daemon_config.functions.get('VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS').call(
                block_identifier=blockstamp.block_hash)
        )
        operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        operator_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

        self.staking_module_id = {
            operator.staking_module.staking_module_address: operator.staking_module.id
            for operator in operators
        }

        self.lido_node_operator_stats = self._prepare_lido_node_operator_stats(
            blockstamp, operators, operator_validators
        )
        self.total_predictable_validators_count = len([
            validator for validator in self.w3.cc.get_validators(blockstamp.state_root)
            if not self._is_on_exit(validator) or self._is_pending(validator)
        ])

    def _no_index_by_validator(self, validator: LidoValidator) -> NodeOperatorIndex:
        return StakingModuleId(self.staking_module_id[validator.key.moduleAddress]), NodeOperatorId(validator.key.operatorIndex)

    def __iter__(self):
        return self

    def __next__(self):
        while self.left_queue_count < self.max_validators_to_exit:
            self.exitable_lido_validators.sort(key=lambda validator: self._predicates(validator))
            to_exit = self.exitable_lido_validators.pop(0)
            self._decrease_node_operator_stats(to_exit)
            self.left_queue_count += 1
            return to_exit
        raise StopIteration

    def _decrease_node_operator_stats(self, validator: LidoValidator) -> None:
        """
        Sub particular validator stats from its node operator stats
        We do it every time when validator is popped from the queue for resort the rest of queue
        """
        module_operator = self._no_index_by_validator(validator)
        self.total_predictable_validators_count -= 1
        self.lido_node_operator_stats[module_operator].predictable_validators_count -= 1
        self.lido_node_operator_stats[module_operator].predictable_validators_total_age -= max(
            0, self.blockstamp.ref_epoch - int(validator.validator.validator.activation_epoch)
        )

    # -- Predicates for sorting validators --
    def _predicates(self, validator: LidoValidator) -> tuple:
        module_operator = self._no_index_by_validator(validator)
        operator_stats = self.lido_node_operator_stats[module_operator]
        return (
            # positive mean asc sorting
            # negative mean desc sorting
            self._operator_delayed_validators(operator_stats),
            -self._operator_targeted_validators_to_exit(operator_stats),
            -self._operator_stake_weight(operator_stats, self.total_predictable_validators_count),
            -self._operator_predictable_validators(operator_stats),
            self._validator_activation_epoch(validator),
            self._validator_index(validator),
        )

    @staticmethod
    def _operator_delayed_validators(operator_state: NodeOperatorPredictableState) -> int:
        return operator_state.delayed_validators

    @staticmethod
    def _operator_targeted_validators_to_exit(operator_state: NodeOperatorPredictableState) -> int:
        if operator_state.targeted_validators is None:
            return 0
        return operator_state.predictable_validators_count - operator_state.targeted_validators

    @staticmethod
    def _operator_stake_weight(
        operator_state: NodeOperatorPredictableState,
        total_predictable_validators_count: int,
    ) -> int:
        stake_volume = 100 * operator_state.predictable_validators_count / total_predictable_validators_count
        stake_volume_weight = operator_state.predictable_validators_total_age if stake_volume > 1 else 0
        return stake_volume_weight

    @staticmethod
    def _operator_predictable_validators(operator_state: NodeOperatorPredictableState) -> int:
        return operator_state.predictable_validators_count

    @staticmethod
    def _validator_activation_epoch(validator: LidoValidator) -> int:
        return int(validator.validator.validator.activation_epoch)

    @staticmethod
    def _validator_index(validator: LidoValidator) -> int:
        return int(validator.validator.index)

    #  -- Internal methods to interact with operators state for sorting --
    def _prepare_lido_node_operator_stats(
        self,
        blockstamp: BlockStamp,
        operators: list[NodeOperator],
        operator_validators: dict[NodeOperatorIndex, list[LidoValidator]]
    ) -> dict[NodeOperatorIndex, NodeOperatorPredictableState]:
        """
        Prepare node operators stats for sorting their validators in exit queue
        """

        # We don't consider validator as delayed if it was requested to exit
        # in last VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS slots
        recently_requested_to_exit_indices_per_operator = self._get_recently_requested_to_exit_indices(
            blockstamp, operator_validators.keys()
        )
        last_requested_to_exit_indices_per_operator = self._get_last_requested_to_exit_indices(
            blockstamp, operator_validators.keys()
        )

        delayed_validators_count = self._get_delayed_validators_count_per_operator(
            operator_validators,
            recently_requested_to_exit_indices_per_operator,
            last_requested_to_exit_indices_per_operator,
        )

        operator_predictable_states: dict[NodeOperatorIndex, NodeOperatorPredictableState] = {}
        for operator in operators:
            module_operator = (operator.staking_module.id, operator.id)

            # Set initial values
            operator_predictable_states[module_operator] = NodeOperatorPredictableState(
                predictable_validators_total_age=0,
                predictable_validators_count=operator.total_deposited_validators,
                targeted_validators=operator.target_validators_count if operator.is_target_limit_active else None,
                delayed_validators=max(
                    0, delayed_validators_count[module_operator] - operator.refunded_validators_count
                ),
            )

            for validator in operator_validators[module_operator]:
                on_exit = self._is_on_exit(validator.validator)
                previously_requested_to_exit = (
                    int(validator.validator.index) <= last_requested_to_exit_indices_per_operator[module_operator]
                )
                if on_exit or previously_requested_to_exit:
                    # We already counted this validator in initial values (total_deposited_validators).
                    # Need to decrease it if it's on exit
                    operator_predictable_states[module_operator].predictable_validators_count -= 1
                    continue
                validator_age = max(0, blockstamp.ref_epoch - int(validator.validator.validator.activation_epoch))
                operator_predictable_states[module_operator].predictable_validators_total_age += validator_age

        return operator_predictable_states

    def _get_last_requested_to_exit_indices(
        self, blockstamp: BlockStamp, operator_indexes: Iterable[NodeOperatorIndex],
    ) -> dict[NodeOperatorIndex, int]:
        """
        Get last requested to exit validator index for each operator
        """
        module_operator_ids = defaultdict(set)
        for module_id, operator_id in operator_indexes:
            module_operator_ids[module_id].add(operator_id)

        last_requested_to_exit_indexes = {}
        for module_id, operator_ids in module_operator_ids.items():
            per_operator_indexes = self._get_last_requested_validator_index(blockstamp, module_id, list(operator_ids))
            for array_index, operator_id in enumerate(operator_ids):
                last_requested_to_exit_indexes[(module_id, operator_id)] = per_operator_indexes[array_index]
        return last_requested_to_exit_indexes

    def _get_delayed_validators_count_per_operator(
        self,
        operator_validators: dict[NodeOperatorIndex, list[LidoValidator]],
        recently_requested_to_exit_indices_per_operator: dict[NodeOperatorIndex, set[int]],
        last_requested_to_exit_indices_per_operator: dict[NodeOperatorIndex, int],
    ) -> dict[NodeOperatorIndex, int]:
        """
        Get delayed validators count for each operator
        """

        delayed_validators_count = defaultdict(int)

        for module_operator, validators in operator_validators.items():
            recently_requested_to_exit_indices = recently_requested_to_exit_indices_per_operator[module_operator]
            for validator in validators:
                previously_requested_to_exit = (
                    int(validator.validator.index) <= last_requested_to_exit_indices_per_operator[module_operator]
                )
                on_exit = self._is_on_exit(validator.validator)
                recently_requested_to_exit = int(validator.validator.index) in recently_requested_to_exit_indices
                if previously_requested_to_exit and not on_exit and not recently_requested_to_exit:
                    delayed_validators_count[module_operator] += 1

        return delayed_validators_count

    def _get_recently_requested_to_exit_indices(
        self,
        blockstamp: BlockStamp,
        operator_indexes: Iterable[NodeOperatorIndex],
    ) -> dict[NodeOperatorIndex, set[int]]:
        """
        Returns recently requested to exit validators indices per operator

        We should get events between two time points - `ref_slot timestamp` and
        `ref_slot - VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS timestamp`
        But we can't get events by time, so we should get events between two exited blocks and filter them by timestamp
        """
        #
        #   [ ] - slot
        #   [x] - slot with existed block
        #   [o] - slot with missed block
        #    e  - event
        #
        #   VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS = 10 (for example)
        #   ref_slot = 22
        #   block_number = 13
        #
        #   timeout_border = ref_slot - VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS = 22 - 10 = 12
        #   timeout_border_timestamp = timeout_border * SLOT_DURATION + genesis_time = 6 * 12 = 96
        #   to_block = block_number = 13
        #   from_block = to_block - VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS = 13 - 10 = 3
        #
        #
        #                  [--------------- Event search block period -------------]
        #                                                  (---- Needed events ----]
        #              from_block                      timeout_border            to_block       ref_slot
        #                  |                               |                       |               |
        #      e           e   e       e           e       e       e           e   e               v   e   e
        #   --[x]-[o]-[x]-[x]-[x]-[x]-[x]-[o]-[o]-[x]-[x]-[x]-[o]-[x]-[x]-[o]-[x]-[x]-[o]-[o]-[o]-[o]-[x]-[x]----> time
        #      1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19  20  21  22  23  24       slot
        #      1   -   2   3   4   5   6   -   -   7   8   9   -  10  11   -  12  13   -   -   -   -  14  15       block
        #
        #   So we should consider events from blocks [10, 12, 13]
        #
        #

        module_operator = {}

        # Initialize dict with empty sets for operators which validators were not contained in any event
        for operator in operator_indexes:
            module_operator[operator] = set()

        timeout_border = max(0, blockstamp.ref_slot - self.validator_delayed_timeout_in_slots)
        timeout_border_timestamp = timeout_border * self.c_conf.seconds_per_slot + self.c_conf.genesis_time

        to_block = blockstamp.block_number
        from_block = max(0, to_block - self.validator_delayed_timeout_in_slots)
        events = self._get_validator_exit_events(from_block, to_block)
        for event in events:
            module_id, operator_id, val_index, val_key, timestamp = event['args']
            if timestamp <= timeout_border_timestamp:
                # We don't consider events that were emitted before or on timeout border
                # So we get a small bunch of events that are considered as "recently". Look at the example above
                continue
            module_operator[(module_id, operator_id)].add(val_index)

        return module_operator

    def _get_last_requested_validator_index(
        self, blockstamp: BlockStamp, module: StakingModuleId, operator_indexes: list[NodeOperatorId]
    ) -> list[int]:
        """
        Returns the latest validator indices that were requested to exit for the given
        `operator_indexes` in the given `module`. For node operators that were never requested to exit
        any validator, index is set to -1.
        """
        return self.w3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices(
            module, operator_indexes
        ).call(
            block_identifier=blockstamp.block_hash
        )

    def _get_validator_exit_events(self, from_block: int, to_block: int) -> list[EventData]:
        return self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest.get_logs(
            fromBlock=from_block, toBlock=to_block
        )

    @staticmethod
    def _is_on_exit(validator: Validator) -> bool:
        return int(validator.validator.exit_epoch) != FAR_FUTURE_EPOCH

    @staticmethod
    def _is_pending(validator: Validator) -> bool:
        return int(validator.validator.activation_epoch) == FAR_FUTURE_EPOCH
