import logging
from copy import deepcopy
from functools import reduce

from eth_typing import HexStr
from more_itertools import ilen

from src.metrics.prometheus.accounting import (
    ACCOUNTING_EXITED_VALIDATORS,
    ACCOUNTING_DELAYED_VALIDATORS,
)
from src.modules.submodules.types import ChainConfig
from src.types import BlockStamp, ReferenceBlockStamp, EpochNumber, OperatorsValidatorCount
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.events import get_events_in_past
from src.utils.types import bytes_to_hex_str
from src.utils.validator_state import is_exited_validator, is_validator_eligible_to_exit, is_on_exit
from src.web3py.extensions.lido_validators import (
    NodeOperatorGlobalIndex,
    LidoValidator,
)
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class LidoValidatorStateService:
    """Helper that calculates/aggregates Lido validator's states."""

    def __init__(self, w3: Web3):
        self.w3 = w3

    def get_last_requested_to_exit_pubkeys(self, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig) -> set[HexStr]:
        exiting_keys_stuck_border_in_slots = self.w3.lido_contracts.oracle_daemon_config.validator_delinquent_timeout_in_slots(
            blockstamp.block_hash,
        )

        events = get_events_in_past(
            self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,  # type: ignore[arg-type]
            to_blockstamp=blockstamp,
            for_slots=exiting_keys_stuck_border_in_slots,
            seconds_per_slot=chain_config.seconds_per_slot,
        )

        logger.info({'msg': f'Fetch exit events. Got {len(events)} events.'})

        return set(bytes_to_hex_str(event['args']['validatorPubkey']) for event in events)

    @lru_cache(maxsize=1)
    def get_operators_with_last_exited_validator_indexes(self, blockstamp: BlockStamp) -> OperatorsValidatorCount:
        result = {}

        staking_modules = self.w3.lido_contracts.staking_router.get_staking_modules(blockstamp.block_hash)
        node_operators = self.w3.lido_validators.get_lido_node_operators_by_modules(blockstamp)

        for module in staking_modules:
            last_requested_ids = self.w3.lido_contracts.validators_exit_bus_oracle.get_last_requested_validator_indices(
                module.id,
                tuple(no.id for no in node_operators[module.id]),
                blockstamp.block_hash,
            )

            result.update({
                (module.id, no.id): last_requested_id
                for no, last_requested_id in zip(node_operators[module.id], last_requested_ids)
            })

        return result

    @lru_cache(maxsize=1)
    def get_lido_newly_exited_validators(self, blockstamp: ReferenceBlockStamp) -> OperatorsValidatorCount:
        lido_validators = deepcopy(self.get_exited_lido_validators(blockstamp))
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)

        for operator in node_operators:
            global_index = (operator.staking_module.id, operator.id)
            ACCOUNTING_EXITED_VALIDATORS.labels(*global_index).set(lido_validators[global_index])
            # If amount of exited validators weren't changed skip report for operator
            if lido_validators[global_index] == operator.total_exited_validators:
                del lido_validators[global_index]

        logger.info({'msg': 'Fetch new lido exited validators by node operator.', 'value': lido_validators})
        return lido_validators

    @lru_cache(maxsize=1)
    def get_exited_lido_validators(self, blockstamp: ReferenceBlockStamp) -> OperatorsValidatorCount:
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

        result = {}

        for global_no_index in lido_validators.keys():
            result[global_no_index] = reduce(
                lambda total, validator: total + int(is_exited_validator(validator, blockstamp.ref_epoch)),
                lido_validators[global_no_index],
                0,
            )

        return result

    @lru_cache(maxsize=1)
    def get_recently_requested_but_not_exited_validators(
        self,
        blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ) -> list[LidoValidator]:
        """
        Returns list of validators recently requested to exit (exit deadline slot in future).

        The deadline slot after which validators are delayed:
        validator_delayed_deadline_slot = max(
            (activation_epoch + SHARD_COMMITTEE_PERIOD),  # For validators that were not able to exit cause of restrictions of the chain
            epoch_when_validator_was_requested_to_exit,
        ) * slots_per_epoch + VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS
        """
        lido_validators_by_operator = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        ejected_indexes = self.get_operators_with_last_exited_validator_indexes(blockstamp)
        recent_indexes = self.get_recently_requested_validators_by_operator(
            chain_config.seconds_per_slot,
            blockstamp,
        )

        validators_recently_requested_to_exit: list[LidoValidator] = []

        for global_index, validators in lido_validators_by_operator.items():

            def validator_requested_to_exit(validator: LidoValidator) -> bool:
                return validator.index <= ejected_indexes[global_index]

            def validator_recently_requested_to_exit(validator: LidoValidator) -> bool:
                return validator.index in recent_indexes[global_index]

            def validator_eligible_to_exit(validator: LidoValidator) -> bool:
                vals_delayed = self.w3.lido_contracts.oracle_daemon_config.validator_delayed_timeout_in_slots(blockstamp.block_hash)
                delayed_timeout_in_epoch = vals_delayed // chain_config.slots_per_epoch
                return is_validator_eligible_to_exit(validator, EpochNumber(blockstamp.ref_epoch - delayed_timeout_in_epoch))

            def is_validator_recently_requested_but_not_exited(validator: LidoValidator) -> bool:
                if not validator_requested_to_exit(validator):
                    return False

                if is_on_exit(validator):
                    return False

                if validator_recently_requested_to_exit(validator):
                    return True

                if not validator_eligible_to_exit(validator):
                    return True

                return False

            def is_validator_delayed(validator: LidoValidator) -> bool:
                return (
                    validator_requested_to_exit(validator) and
                    not is_on_exit(validator) and
                    not validator_recently_requested_to_exit(validator) and
                    validator_eligible_to_exit(validator)
                )

            validators_recently_requested_to_exit.extend(
                filter(is_validator_recently_requested_but_not_exited, validators)
            )
            delayed_validators_count = ilen(filter(is_validator_delayed, validators))

            ACCOUNTING_DELAYED_VALIDATORS.labels(*global_index).set(delayed_validators_count)

        return validators_recently_requested_to_exit

    def get_recently_requested_validators_by_operator(
        self,
        seconds_per_slot: int,
        blockstamp: ReferenceBlockStamp,
    ) -> dict[NodeOperatorGlobalIndex, set[int]]:
        """
        Returns validators indexes that were asked to exit in last {{validator_delayed_timeout_in_slots}} slots.
        """
        exiting_keys_delayed_border_in_slots = self.w3.lido_contracts.oracle_daemon_config.validator_delayed_timeout_in_slots(blockstamp.block_hash)

        events = get_events_in_past(
            self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,  # type: ignore[arg-type]
            to_blockstamp=blockstamp,
            for_slots=exiting_keys_delayed_border_in_slots,
            seconds_per_slot=seconds_per_slot,
        )

        logger.info({'msg': f'Fetch exit events. Got {len(events)} events.'})

        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        # Initialize dict with empty sets for operators which validators were not contained in any event
        global_indexes: dict[NodeOperatorGlobalIndex, set[int]] = {
            (operator.staking_module.id, operator.id): set() for operator in node_operators
        }

        for event in events:
            operator_global_index = (event['args']['stakingModuleId'], event['args']['nodeOperatorId'])
            global_indexes[operator_global_index].add(event['args']['validatorIndex'])

        return global_indexes
