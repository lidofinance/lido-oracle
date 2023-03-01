import logging
from copy import deepcopy
from functools import lru_cache, reduce
from typing import Sequence

from eth_typing import HexStr

from src.constants import FAR_FUTURE_EPOCH, SHARD_COMMITTEE_PERIOD
from src.modules.accounting.extra_data import ExtraDataService, ExtraData
from src.modules.accounting.typings import OracleReportLimits
from src.modules.submodules.typings import ChainConfig
from src.typings import BlockStamp, ReferenceBlockStamp, EpochNumber
from src.utils.abi import named_tuple_to_dataclass
from src.utils.events import get_events_in_past
from src.utils.types import bytes_to_hex_str
from src.utils.validator_state import is_exited_validator, is_validator_eligible_to_exit, is_on_exit
from src.web3py.extentions.lido_validators import (
    NodeOperatorGlobalIndex,
    LidoValidator,
    StakingModule,
)
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class LidoValidatorStateService:
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.extra_data_service = ExtraDataService(w3)

    @lru_cache(maxsize=1)
    def get_extra_data(self, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig) -> ExtraData:
        stuck_validators = self.get_lido_newly_stuck_validators(blockstamp, chain_config)
        logger.info({'msg': 'Calculate stuck validators.', 'value': stuck_validators})
        exited_validators = self.get_lido_newly_exited_validators(blockstamp)
        logger.info({'msg': 'Calculate exited validators.', 'value': exited_validators})
        orl = self._get_oracle_report_limits(blockstamp)

        extra_data = self.extra_data_service.collect(
            stuck_validators=stuck_validators,
            exited_validators=exited_validators,
            max_items_in_payload_count=orl.max_accounting_extra_data_list_items_count,
            max_items_count=orl.max_accounting_extra_data_list_items_count,
        )
        logger.info({'msg': 'Calculate extra data.', 'value': extra_data})
        return extra_data

    def get_lido_newly_stuck_validators(self, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig) -> dict[NodeOperatorGlobalIndex, int]:
        lido_validators_by_no = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        ejected_index = self.get_operators_with_last_exited_validator_indexes(blockstamp)
        recently_asked_to_exit_pubkeys = self.get_last_requested_to_exit_pubkeys(blockstamp, chain_config)

        result = {}

        for global_no_index, validators in lido_validators_by_no.items():
            def sum_stuck_validators(total: int, validator: LidoValidator) -> int:
                # If validator index is higher than ejected index - we didn't asked this validator to exit
                if int(validator.index) > ejected_index[global_no_index]:
                    return total

                # If validator don't have FAR_FUTURE_EPOCH, then it's already going to exit
                if int(validator.validator.exit_epoch) != FAR_FUTURE_EPOCH:
                    return total

                # If validator's pub key in recent events, node operator has still time to eject these validators
                if validator.lido_id.key in recently_asked_to_exit_pubkeys:
                    return total

                validator_available_to_exit_epoch = int(validator.validator.activation_epoch) + SHARD_COMMITTEE_PERIOD
                delinquent_timeout_in_slots = self.get_validator_delinquent_timeout_in_slot(blockstamp)

                last_slot_to_exit = validator_available_to_exit_epoch * chain_config.slots_per_epoch + delinquent_timeout_in_slots

                if blockstamp.ref_slot < last_slot_to_exit:
                    return total

                return total + 1

            result[global_no_index] = reduce(
                sum_stuck_validators,
                validators,
                0,
            )

        # Find only updated states for Node Operator
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)

        for operator in node_operators:
            # If amount of exited validators weren't changed skip report for operator
            if result[(operator.staking_module.id, operator.id)] == operator.stuck_validators_count:
                del result[(operator.staking_module.id, operator.id)]

        return result

    def get_last_requested_to_exit_pubkeys(self, blockstamp: ReferenceBlockStamp, chain_config: ChainConfig) -> set[HexStr]:
        exiting_keys_stuck_border_in_slots = self.get_validator_delinquent_timeout_in_slot(blockstamp)

        events = get_events_in_past(
            self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,
            to_blockstamp=blockstamp,
            for_slots=exiting_keys_stuck_border_in_slots,
            seconds_per_slot=chain_config.seconds_per_slot,
        )

        logger.info({'msg': f'Fetch exit events. Got {len(events)} events.'})

        return set(bytes_to_hex_str(event['args']['validatorPubkey']) for event in events)

    @lru_cache(maxsize=1)
    def get_validator_delinquent_timeout_in_slot(self, blockstamp: ReferenceBlockStamp) -> int:
        exiting_keys_stuck_border_in_slots_bytes = self.w3.lido_contracts.oracle_daemon_config.functions.get(
            'VALIDATOR_DELINQUENT_TIMEOUT_IN_SLOTS'
        ).call(block_identifier=blockstamp.block_hash)

        return self.w3.to_int(exiting_keys_stuck_border_in_slots_bytes)

    def get_operators_with_last_exited_validator_indexes(self, blockstamp: BlockStamp) -> dict[NodeOperatorGlobalIndex, int]:
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        staking_modules = self.w3.lido_validators.get_staking_modules(blockstamp)

        result = {}

        for module in staking_modules:
            node_operators_ids_in_module = list(map(lambda op: op.id, filter(lambda operator: operator.staking_module.id == module.id, node_operators)))

            last_requested_validators = self._get_last_requested_validator_indices(blockstamp, module, node_operators_ids_in_module)

            for no_id, validator_index in zip(node_operators_ids_in_module, last_requested_validators):
                result[(module.id, no_id)] = validator_index

        return result

    @lru_cache(maxsize=1)
    def get_lido_newly_exited_validators(self, blockstamp: ReferenceBlockStamp) -> dict[NodeOperatorGlobalIndex, int]:
        lido_validators = deepcopy(self.get_exited_lido_validators(blockstamp))
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)

        for operator in node_operators:
            # If amount of exited validators weren't changed skip report for operator
            if lido_validators[(operator.staking_module.id, operator.id)] == operator.total_exited_validators:
                del lido_validators[(operator.staking_module.id, operator.id)]

        logger.info({'msg': 'Fetch new lido exited validators by node operator.', 'value': lido_validators})
        return lido_validators

    @lru_cache(maxsize=1)
    def get_exited_lido_validators(self, blockstamp: ReferenceBlockStamp) -> dict[NodeOperatorGlobalIndex, int]:
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

        result = {}

        for global_no_index in lido_validators.keys():
            result[global_no_index] = reduce(
                lambda total, validator: total + int(is_exited_validator(validator, blockstamp.ref_epoch)),
                lido_validators[global_no_index],
                0,
            )

        return result

    def _get_oracle_report_limits(self, blockstamp: BlockStamp) -> OracleReportLimits:
        result = self.w3.lido_contracts.oracle_report_sanity_checker.functions.getOracleReportLimits().call(
            block_identifier=blockstamp.block_hash,
        )
        orl = named_tuple_to_dataclass(result, OracleReportLimits)
        logger.info({'msg': 'Fetch oracle sanity checks.', 'value': orl})
        return orl

    def _get_last_requested_validator_indices(self, blockstamp: BlockStamp, module: StakingModule, node_operators_ids_in_module: Sequence[int]) -> list[int]:
        return self.w3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices(
            module.id,
            node_operators_ids_in_module,
        ).call(block_identifier=blockstamp.block_hash)

    def get_recently_requested_but_not_exited_validators(
        self, blockstamp: ReferenceBlockStamp,
        chain_config: ChainConfig,
    ) -> list[LidoValidator]:
        """
        Validators requested to exit, but didn't send exit message.
        In case:
        - Activation epoch is not old enough to initiate exit
        - Node operator had not enough time to send exit message (VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS)
        """
        lido_validators_by_no = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        ejected_index = self.get_operators_with_last_exited_validator_indexes(blockstamp)
        recent_pubkeys = self.get_recently_requests_to_exit_pubkeys(blockstamp, chain_config)

        validators_recently_requested_to_exit = []

        for global_no_index, validators in lido_validators_by_no.items():
            def validator_asked_to_exit(validator: LidoValidator) -> bool:
                return int(validator.index) <= ejected_index[global_no_index]

            def validator_recently_asked_to_exit(validator: LidoValidator) -> bool:
                return validator.validator.pubkey in recent_pubkeys

            def validator_eligible_to_exit(validator: LidoValidator) -> bool:
                delayed_timeout_in_epoch = self.get_validator_delayed_timeout_in_slot(blockstamp) // chain_config.slots_per_epoch
                return is_validator_eligible_to_exit(validator, EpochNumber(blockstamp.ref_epoch - delayed_timeout_in_epoch))

            def non_exited_validators(validator: LidoValidator) -> bool:
                if not validator_asked_to_exit(validator):
                    return False

                if is_on_exit(validator):
                    return False

                if validator_recently_asked_to_exit(validator):
                    return True

                if not validator_eligible_to_exit(validator):
                    return True

                return False

            validators_recently_requested_to_exit.extend(
                list(filter(non_exited_validators, validators))
            )

        return validators_recently_requested_to_exit

    def get_recently_requests_to_exit_pubkeys(
            self, blockstamp: ReferenceBlockStamp,
            chain_config: ChainConfig,
    ) -> set[HexStr]:
        exiting_keys_delayed_border_in_slots = self.get_validator_delayed_timeout_in_slot(blockstamp)

        events = get_events_in_past(
            self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,
            to_blockstamp=blockstamp,
            for_slots=exiting_keys_delayed_border_in_slots,
            seconds_per_slot=chain_config.seconds_per_slot,
        )

        logger.info({'msg': f'Fetch exit events. Got {len(events)} events.'})

        return set(bytes_to_hex_str(event['args']['validatorPubkey']) for event in events)

    @lru_cache(maxsize=1)
    def get_validator_delayed_timeout_in_slot(self, blockstamp: ReferenceBlockStamp) -> int:
        exiting_keys_delayed_border_in_slots_bytes = self.w3.lido_contracts.oracle_daemon_config.functions.get(
            'VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS'
        ).call(block_identifier=blockstamp.block_hash)

        return self.w3.to_int(exiting_keys_delayed_border_in_slots_bytes)
