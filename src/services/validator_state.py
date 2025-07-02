import logging
from copy import deepcopy
from functools import reduce

from src.metrics.prometheus.accounting import ACCOUNTING_EXITED_VALIDATORS
from src.modules.submodules.types import ChainConfig
from src.types import OperatorsValidatorCount, ReferenceBlockStamp
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.events import get_events_in_past
from src.utils.validator_state import is_exited_validator, is_on_exit
from src.web3py.extensions.lido_validators import (LidoValidator, NodeOperatorGlobalIndex)
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class LidoValidatorStateService:
    """Helper that calculates/aggregates Lido validator's states."""

    def __init__(self, w3: Web3):
        self.w3 = w3

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
        """
        lido_validators_by_operator = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        recent_exit_requests = self.get_recently_requested_to_exit_validators_by_node_operator(
            chain_config.seconds_per_slot,
            blockstamp,
        )

        validators_recently_requested_to_exit: list[LidoValidator] = []

        for global_index, validators in lido_validators_by_operator.items():
            def is_validator_recently_requested_but_not_exited(validator: LidoValidator) -> bool:
                # Validator is not exiting on CL and there is recent exit request event
                return not is_on_exit(validator) and validator.index in recent_exit_requests[global_index]

            validators_recently_requested_to_exit.extend(
                filter(is_validator_recently_requested_but_not_exited, validators)
            )

        return validators_recently_requested_to_exit

    @lru_cache(maxsize=1)
    def get_recently_requested_to_exit_validators_by_node_operator(
        self,
        seconds_per_slot: int,
        blockstamp: ReferenceBlockStamp,
    ) -> dict[NodeOperatorGlobalIndex, set[int]]:
        """
        Returns validators indexes that were asked to exit in last {{lookup_window}} slots.
        """
        lookup_window = self.w3.lido_contracts.oracle_daemon_config.exit_events_lookback_window_in_slots(blockstamp.block_hash)

        events = get_events_in_past(
            self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,  # type: ignore[arg-type]
            to_blockstamp=blockstamp,
            for_slots=lookup_window,
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
