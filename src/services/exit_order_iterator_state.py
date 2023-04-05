from dataclasses import dataclass

from more_itertools import ilen

from src.constants import TOTAL_BASIS_POINTS
from src.modules.submodules.typings import ChainConfig
from src.services.validator_state import LidoValidatorStateService
from src.typings import ReferenceBlockStamp
from src.utils.validator_state import is_on_exit, get_validator_age
from src.web3py.extensions.lido_validators import NodeOperatorGlobalIndex, LidoValidator
from src.web3py.typings import Web3


@dataclass
class NodeOperatorPredictableState:
    predictable_validators_total_age: int
    predictable_validators_count: int
    targeted_validators_limit_is_enabled: bool
    targeted_validators_limit_count: int
    delayed_validators_count: int


class ExitOrderIteratorStateService(LidoValidatorStateService):
    """Service prepares lido operator statistic, which used to form validators queue in right order"""

    def __init__(self, web3: Web3, blockstamp: ReferenceBlockStamp):
        super().__init__(web3)

        self._operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        self._operator_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        self._operator_last_requested_to_exit_indexes = self.get_operators_with_last_exited_validator_indexes(
            blockstamp
        )

    def get_exitable_lido_validators(self) -> list[LidoValidator]:
        """Get validators that are available to exit"""

        exitable_lido_validators = []

        for global_index, validators in self._operator_validators.items():
            last_requested_to_exit_index = self._operator_last_requested_to_exit_indexes[global_index]
            for validator in validators:
                if self.is_exitable(validator, last_requested_to_exit_index):
                    exitable_lido_validators.append(validator)

        return exitable_lido_validators

    def prepare_lido_node_operator_stats(
        self, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig
    ) -> dict[NodeOperatorGlobalIndex, NodeOperatorPredictableState]:
        """Prepare node operators stats for sorting their validators in exit order"""

        recently_requested_to_exit_indexes_per_operator = self.get_recently_requests_to_exit_indexes_by_operators(
            blockstamp, chain_config, self._operator_validators.keys()
        )

        operator_predictable_stats: dict[NodeOperatorGlobalIndex, NodeOperatorPredictableState] = {}
        for operator in self._operators:
            global_index = (operator.staking_module.id, operator.id)

            operator_validators = self._operator_validators[global_index]
            recently_to_exit_indexes = recently_requested_to_exit_indexes_per_operator[global_index]
            last_to_exit_index = self._operator_last_requested_to_exit_indexes[global_index]

            # Validators that are not yet in CL
            transient_validators_count = operator.total_deposited_validators - len(operator_validators)

            # Validators that are in CL and are not yet requested to exit and not on exit
            predictable_validators_total_age, predictable_validators_count = self.count_operator_validators_stats(
                blockstamp, operator_validators, last_to_exit_index
            )

            # Validators that are in CL and requested to exit but not on exit and not requested to exit recently
            delayed_validators_count = self.count_operator_delayed_validators(
                operator_validators,
                recently_to_exit_indexes,
                last_to_exit_index,
            )

            operator_predictable_stats[global_index] = NodeOperatorPredictableState(
                predictable_validators_total_age,
                transient_validators_count + predictable_validators_count,
                operator.is_target_limit_active,
                operator.target_validators_count,
                max(0, delayed_validators_count - operator.refunded_validators_count)
            )

        return operator_predictable_stats

    def get_total_predictable_validators_count(
        self,
        blockstamp: ReferenceBlockStamp,
        lido_node_operator_stats: dict[NodeOperatorGlobalIndex, NodeOperatorPredictableState]
    ) -> int:
        """Get total predictable validators count for stake weight calculation"""
        lido_validators = {
            v.validator.pubkey: v for v in self.w3.lido_validators.get_lido_validators(blockstamp)
        }
        not_lido_predictable_validators_count = ilen(
            v for v in self.w3.cc.get_validators(blockstamp)
            if v.validator.pubkey not in lido_validators and not is_on_exit(v)
        )
        lido_predictable_validators_count = sum(
            o.predictable_validators_count for o in lido_node_operator_stats.values()
        )
        return (
            not_lido_predictable_validators_count + lido_predictable_validators_count
        )

    def get_operator_network_penetration_threshold(self, blockstamp: ReferenceBlockStamp) -> float:
        exiting_keys_delayed_border_in_slots_bytes = self.w3.lido_contracts.oracle_daemon_config.functions.get(
            'NODE_OPERATOR_NETWORK_PENETRATION_THRESHOLD_BP'
        ).call(block_identifier=blockstamp.block_hash)

        return self.w3.to_int(exiting_keys_delayed_border_in_slots_bytes) / TOTAL_BASIS_POINTS

    @staticmethod
    def count_operator_validators_stats(
        blockstamp: ReferenceBlockStamp,
        operator_validators: list[LidoValidator],
        last_requested_to_exit_index: int,
    ) -> tuple[int, int]:
        """Get operator validators stats for sorting their validators in exit queue"""

        predictable_validators_total_age = 0
        predictable_validators_count = 0
        for validator in operator_validators:
            if ExitOrderIteratorStateService.is_exitable(validator, last_requested_to_exit_index):
                predictable_validators_total_age += get_validator_age(validator, blockstamp.ref_epoch)
                predictable_validators_count += 1

        return predictable_validators_total_age, predictable_validators_count

    @staticmethod
    def count_operator_delayed_validators(
        operator_validators: list[LidoValidator],
        recently_operator_requested_to_exit_index: set[int],
        last_requested_to_exit_index: int,
    ) -> int:
        """Get delayed validators count for each operator"""

        delayed_validators_count = 0

        for validator in operator_validators:
            requested_to_exit = int(validator.index) <= last_requested_to_exit_index
            on_exit = is_on_exit(validator)
            recently_requested_to_exit = int(validator.index) in recently_operator_requested_to_exit_index
            if requested_to_exit and not on_exit and not recently_requested_to_exit:
                delayed_validators_count += 1

        return delayed_validators_count

    @staticmethod
    def is_exitable(validator: LidoValidator, last_requested_to_exit_index: int) -> bool:
        """Returns True if validator is exitable: not on exit and not requested to exit"""
        requested_to_exit = int(validator.index) <= last_requested_to_exit_index
        on_exit = is_on_exit(validator)
        exitable = not on_exit and not requested_to_exit
        return exitable
