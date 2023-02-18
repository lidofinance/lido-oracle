from copy import deepcopy
from functools import lru_cache

from src.modules.accounting.extra_data import ExtraDataService, ExtraData
from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import (
    NodeOperatorIndex,
    LidoValidator,
    ValidatorsByNodeOperator,
)
from src.web3py.typings import Web3


FAR_FUTURE_EPOCH = 2 ** 64 - 1


class LidoValidatorStateService:
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.extra_data_service = ExtraDataService(w3)

    def get_extra_data_hash(self, blockstamp: BlockStamp):
        e_data = self.get_extra_data(blockstamp)
        return self.w3.keccak(e_data)

    @lru_cache(maxsize=1)
    def get_extra_data(self, blockstamp: BlockStamp) -> ExtraData:
        exited_validators = self.get_lido_new_exited_validators(blockstamp)
        stucked_validators = self.get_lido_new_stucked_validators(blockstamp)

        return self.extra_data_service.collect(
            stucked_validators=stucked_validators,
            exited_validators=exited_validators,
        )

    def get_lido_new_stucked_validators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        recently_asked_to_exit_pubkeys = self.get_last_asked_to_exit_pubkeys(blockstamp)
        ejected_index = self.get_operators_with_last_exited_validator_indexes(blockstamp)
        lido_validators_by_no = deepcopy(self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp))
        for key, validators in lido_validators_by_no.items():
            lido_validators_by_no[key] = list(filter(
                lambda validator: validator.validator.validator.exit_epoch == FAR_FUTURE_EPOCH
                                  and validator.validator.index <= ejected_index[key]
                                  and validator.validator.validator.pubkey not in recently_asked_to_exit_pubkeys,
                validators,
            ))

        return lido_validators_by_no

    def get_last_asked_to_exit_pubkeys(self, blockstamp: BlockStamp):
        # TODO fix this
        exiting_keys_stucked_border_in_slots = self.w3.lido_contracts.oracle_daemon_config.functions.get(
            'VALIDATOR_DELINQUENT_TIMEOUT_IN_SLOTS',
        ).call(block_identifier=blockstamp.block_hash)

        # Calculate from block here

        events = self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest.get_logs(
            from_=blockstamp.block_number,
            to=blockstamp.block_number,
        )

        return set(map(lambda event: event['args']['pubkey'], events))

    def get_operators_with_last_exited_validator_indexes(self, blockstamp: BlockStamp) -> dict[NodeOperatorIndex, int]:
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        stacking_modules = self.w3.lido_validators.get_staking_modules(blockstamp)

        result = {}

        for module in stacking_modules:
            node_operators_ids_in_module = list(
                map(lambda op: op.id, filter(lambda operator: operator.staking_module.id == module.id, node_operators)))

            last_ejected_validators = self.w3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices(
                module.id,
                node_operators_ids_in_module,
            )

            for no_id, validator_index in zip(node_operators_ids_in_module, last_ejected_validators):
                result[(module.id, no_id)] = validator_index

        return result

    def get_lido_new_exited_validators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        lido_validators = self._get_exited_lido_validators(blockstamp)
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)

        for operator in node_operators:
            # If amount of exited validators weren't changed skip report for operator
            if len(lido_validators[
                       NodeOperatorIndex(operator.staking_module.id, operator.id)]) == operator.total_exited_validators:
                del lido_validators[NodeOperatorIndex(operator.staking_module.id, operator.id)]

        return lido_validators

    def _get_exited_lido_validators(self, blockstamp: BlockStamp) -> ValidatorsByNodeOperator:
        lido_validators = deepcopy(self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp))

        def exit_filter(validator: LidoValidator) -> bool:
            return int(validator.validator.validator.exit_epoch) < blockstamp.ref_epoch

        for index, validators in lido_validators.items():
            lido_validators[index] = list(filter(exit_filter, lido_validators[index]))

        return lido_validators
