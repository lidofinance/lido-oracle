from collections import defaultdict
from dataclasses import dataclass

from eth_typing import Address

from src.modules.submodules.typings import ChainConfig

from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import LidoValidator, NodeOperator, NodeOperatorIndex
from src.web3py.typings import Web3

FAR_FUTURE_EPOCH = 2 ** 64 - 1
VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS = 3600  # todo: get from contract


@dataclass
class NodeOperatorPredictableState:
    predictable_validators_total_age: int
    predictable_validators_count: int
    targeted_validators: int
    delayed_validators: int


class ValidatorsExit:
    """
    Exit order predicates sequence:
    1. Validator whose operator with the lowest number of delayed validators
    2. Validator whose operator with the highest number of targeted validators
    3. Validator whose operator with the highest stake weight
    4. Validator whose operator with the highest number of validators
    5. Validator with the lowest activation epoch
    6. Validator with the lowest index
    """

    def __init__(
        self,
        blockstamp: BlockStamp,
        w3: Web3,
        c_conf: ChainConfig,
        exitable_lido_validators: list[LidoValidator],
        max_validators_to_exit: int,
    ):
        self.blockstamp = blockstamp
        self.w3 = w3
        self.c_conf = c_conf

        self.exitable_lido_validators = exitable_lido_validators
        self.max_validators_to_exit = max_validators_to_exit

        ###########
        # todo: remove after keys-api fix. Key should contain staking module id, not only address
        operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        self.staking_module_id = {
            operator.staking_module.staking_module_address: operator.staking_module.id
            for operator in operators
        }
        self.no_index_by_validator = (
            lambda v: NodeOperatorIndex(self.staking_module_id[v.key.moduleAddress], v.key.operatorIndex)
        )
        ###########

        self.lido_node_operator_stats = self._prepare_lido_node_operator_stats(blockstamp, operators)
        self.total_predictable_validators = sum(
            operator_state.predictable_validators_count for operator_state in self.lido_node_operator_stats.values()
        )

    def __iter__(self):
        return self

    def __next__(self) -> LidoValidator:
        left_queue_count = 0
        while left_queue_count < self.max_validators_to_exit:
            self.exitable_lido_validators.sort(key=lambda validator: self._predicates(validator))
            to_exit = self.exitable_lido_validators.pop(0)
            yield to_exit
            self._decrease_node_operator_stats(to_exit)
            left_queue_count += 1

    def _decrease_node_operator_stats(self, validator: LidoValidator) -> None:
        """
        Sub particular validator stats from its node operator stats
        We do it every time when validator is popped from the queue for resort the rest of queue
        """
        module_operator = self.no_index_by_validator(validator)
        self.total_predictable_validators -= 1
        self.lido_node_operator_stats[module_operator].predictable_validators_count -= 1
        self.lido_node_operator_stats[module_operator].predictable_validators_total_age -= int(validator.validator.activation_epoch)

    # -- Predicates for sorting validators --
    def _predicates(self, validator: LidoValidator) -> tuple:
        module_operator = self.no_index_by_validator(validator)
        return (
            # positive mean asc sorting
            # negative mean desc sorting
            self._operator_delayed_validators(
                self.lido_node_operator_stats[module_operator]
            ),
            -self._operator_targeted_validators(
                self.lido_node_operator_stats[module_operator],
            ),
            -self._operator_stake_weight(
                self.lido_node_operator_stats[module_operator],
                self.total_predictable_validators
            ),
            -self._operator_predictable_validators(
                self.lido_node_operator_stats[module_operator]
            ),
            self._validator_activation_epoch(validator),
            self._validator_index(validator),
        )

    @staticmethod
    def _operator_delayed_validators(operator_state: NodeOperatorPredictableState) -> int:
        return operator_state.delayed_validators

    @staticmethod
    def _operator_targeted_validators(operator_state: NodeOperatorPredictableState) -> int:
        if operator_state.targeted_validators:
            return max(0, operator_state.predictable_validators_count - operator_state.targeted_validators)
        else:
            return 0

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
        return int(validator.validator.activation_epoch)

    @staticmethod
    def _validator_index(validator: LidoValidator) -> int:
        return int(validator.index)

    #  -- Internal methods to interact with operators state for sorting --
    def _prepare_lido_node_operator_stats(
        self, blockstamp: BlockStamp, operators: list[NodeOperator]
    ) -> dict[NodeOperatorIndex, NodeOperatorPredictableState]:
        """
        Prepare node operators stats for sorting their validators in exit queue
        """
        operator_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

        last_requested_to_exit_indices_per_operator = self._fetch_last_requested_to_exit_indices(
            blockstamp, operator_validators
        )
        delayed_validators_per_operator = self._fetch_delayed_validators_per_operator(
            blockstamp,
            operator_validators,
            last_requested_to_exit_indices_per_operator,
        )

        operator_predictable_states = {}
        for operator in operators:
            module_operator = (operator.staking_module.id, operator.id)

            # Set initial values
            operator_predictable_states[module_operator] = NodeOperatorPredictableState(
                predictable_validators_total_age=0,
                predictable_validators_count=operator.total_deposited_validators,
                targeted_validators=operator.target_validators_count if operator.is_target_limit_active else None,
                delayed_validators=max(
                    0, len(delayed_validators_per_operator[module_operator]) - operator.refunded_validators_count
                ),
            )

            for validator in operator_validators[(operator.staking_module.id, operator.id)]:
                on_exit = self._is_on_exit(validator)
                previously_requested_to_exit = (
                    int(validator.index) <= last_requested_to_exit_indices_per_operator[module_operator]
                )
                if not on_exit or not previously_requested_to_exit:
                    is_pending = self._is_pending(validator)
                    validator_age = 0 if is_pending else blockstamp.ref_epoch - int(validator.validator.activation_epoch)
                    operator_predictable_states[module_operator].predictable_validators_total_age += validator_age
                    operator_predictable_states[module_operator].predictable_validators_count += 1

        return operator_predictable_states

    def _fetch_recently_requested_to_exit_indices(
        self, blockstamp: BlockStamp, operator_validators: dict[NodeOperatorIndex, list[LidoValidator]]
    ) -> dict[NodeOperatorIndex, set[int]]:
        """
        Returns recently requested to exit validators indices per operator
        """
        module_operator = {}

        # Initialize dict with empty sets for operators which validators were not contained in any event
        for operator in operator_validators:
            module_operator[operator] = set()

        from_block = blockstamp.ref_slot - VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS
        to_block = blockstamp.ref_slot
        events = self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest.getLogs(
            fromBlock=from_block, toBlock=to_block
        )
        from_block_timestamp = from_block * self.c_conf.slots_per_epoch
        for event in events:
            module_id, operator_id, val_index, val_key, timestamp = event['args']
            if timestamp < from_block_timestamp:
                continue
            module_operator[(module_id, operator_id)].add(val_index)

        return module_operator

    def _fetch_last_requested_to_exit_indices(
        self, blockstamp: BlockStamp, operator_validators: dict[NodeOperatorIndex, list[LidoValidator]]
    ) -> dict[NodeOperatorIndex, int]:
        """
        Returns the latest validator indices that were requested to exit for the given
        `nodeOpIds` in the given `moduleId`. For node operators that were never requested to exit
        any validator, index is set to -1.
        """
        module_operator_ids = {}
        for module_id, operator_id in operator_validators:
            module_operator_ids.setdefault(module_id, set()).add(operator_id)

        last_requested_to_exit_indexes = {}
        for module_id, operator_ids in module_operator_ids.items():
            operator_ids.sort()
            per_operator_indexes = self._get_last_requested_validator_index(blockstamp, module_id, operator_ids)
            for operator_id in operator_ids:
                last_requested_to_exit_indexes[(module_id, operator_id)] = per_operator_indexes[operator_id]
        return last_requested_to_exit_indexes

    def _fetch_delayed_validators_per_operator(
        self,
        blockstamp: BlockStamp,
        operator_validators: dict[NodeOperatorIndex, list[LidoValidator]],
        last_requested_to_exit_indices_per_operator: dict[NodeOperatorIndex, int],
    ) -> dict[NodeOperatorIndex, dict[int, LidoValidator]]:

        delayed_validators_per_operator = defaultdict(dict[int, LidoValidator])

        recently_requested_to_exit_indices_per_operator = self._fetch_recently_requested_to_exit_indices(
            blockstamp, operator_validators
        )

        for module_operator, validators in operator_validators.items():
            recently_requested_to_exit_indices = recently_requested_to_exit_indices_per_operator[module_operator]
            for validator in validators:
                previously_requested_to_exit = (
                    int(validator.index) <= last_requested_to_exit_indices_per_operator[module_operator]
                )
                on_exit = self._is_on_exit(validator)
                recently_requested_to_exit = int(validator.index) in recently_requested_to_exit_indices
                if previously_requested_to_exit and not on_exit and not recently_requested_to_exit:
                    delayed_validators_per_operator[module_operator][int(validator.index)] = validator

        return delayed_validators_per_operator

    @staticmethod
    def _is_on_exit(validator: LidoValidator) -> bool:
        return validator.validator.exit_epoch != FAR_FUTURE_EPOCH

    @staticmethod
    def _is_pending(validator: LidoValidator) -> bool:
        return validator.validator.activation_epoch == FAR_FUTURE_EPOCH

    def _get_last_requested_validator_index(
        self, blockstamp: BlockStamp, module: Address, operator_indexes: list[int]
    ) -> list[int]:
        return self.w3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndex(
            module, operator_indexes
        ).call(
            block_identifier=blockstamp.block_hash
        )
