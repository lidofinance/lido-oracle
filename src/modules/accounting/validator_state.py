import logging
from functools import lru_cache, reduce

from eth_typing import HexStr

from src.constants import FAR_FUTURE_EPOCH
from src.modules.accounting.extra_data import ExtraDataService, ExtraData
from src.modules.accounting.typings import OracleReportLimits
from src.modules.submodules.typings import ChainConfig
from src.typings import BlockStamp, SlotNumber
from src.utils.abi import named_tuple_to_dataclass
from src.utils.events import get_events_in_past
from src.utils.types import bytes_to_hex_str
from src.web3py.extentions.lido_validators import (
    NodeOperatorIndex,
    LidoValidator,
)
from src.web3py.typings import Web3


logger = logging.getLogger(__name__)


class LidoValidatorStateService:
    def __init__(self, w3: Web3):
        self.w3 = w3
        self.extra_data_service = ExtraDataService(w3)

    @lru_cache(maxsize=1)
    def get_extra_data(self, blockstamp: BlockStamp, chain_config: ChainConfig) -> ExtraData:
        stucked_validators = self.get_lido_new_stucked_validators(blockstamp, chain_config)
        logger.info({'msg': 'Calculate stucked validators.', 'value': stucked_validators})
        exited_validators = self.get_lido_new_exited_validators(blockstamp)
        logger.info({'msg': 'Calculate exited validators.', 'value': exited_validators})
        orl = self._get_oracle_report_limits(blockstamp)

        extra_data = self.extra_data_service.collect(
            stucked_validators=stucked_validators,
            exited_validators=exited_validators,
            max_items_in_payload_count=orl.max_accounting_extra_data_list_items_count,
            max_items_count=orl.max_accounting_extra_data_list_items_count,
        )
        logger.info({'msg': 'Calculate extra data.', 'value': extra_data})
        return extra_data

    def get_lido_new_stucked_validators(self, blockstamp: BlockStamp, chain_config: ChainConfig) -> dict[NodeOperatorIndex, int]:
        lido_validators_by_no = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
        ejected_index = self.get_operators_with_last_exited_validator_indexes(blockstamp)
        recently_asked_to_exit_pubkeys = self.get_last_asked_to_exit_pubkeys(blockstamp, chain_config)

        result = {}

        for key, validators in lido_validators_by_no.items():
            def filter_non_stucked(total: int, validator: LidoValidator) -> int:
                # If validator index is higher than ejected index - we didn't asked this validator to exit
                if int(validator.validator.index) > ejected_index[key]:
                    return total

                # If validator don't have FAR_FUTURE_EPOCH, then it's already going to exit
                if validator.validator.validator.exit_epoch != FAR_FUTURE_EPOCH:
                    return total

                # If validator's pub key in recent events, node operator has steel time to eject this validators
                if validator.key.key in recently_asked_to_exit_pubkeys:
                    return total

                return total + 1

            result[key] = reduce(
                filter_non_stucked,
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

    def get_last_asked_to_exit_pubkeys(self, blockstamp: BlockStamp, chain_config: ChainConfig) -> set[HexStr]:
        exiting_keys_stucked_border_in_slots_bytes = self.w3.lido_contracts.oracle_daemon_config.functions.get(
            'VALIDATOR_DELINQUENT_TIMEOUT_IN_SLOTS'
        ).call(block_identifier=blockstamp.block_hash)

        # parse to int
        exiting_keys_stucked_border_in_slots = int(exiting_keys_stucked_border_in_slots_bytes.hex(), base=16)

        events = get_events_in_past(
            self.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest,
            to_blockstamp=blockstamp,
            for_slots=exiting_keys_stucked_border_in_slots,
            seconds_per_slot=chain_config.seconds_per_slot,
        )

        return set(bytes_to_hex_str(event['args']['validatorPubkey']) for event in events)

    def get_operators_with_last_exited_validator_indexes(self, blockstamp: BlockStamp) -> dict[NodeOperatorIndex, int]:
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)
        stacking_modules = self.w3.lido_validators.get_staking_modules(blockstamp)

        result = {}

        for module in stacking_modules:
            node_operators_ids_in_module = list(map(lambda op: op.id, filter(lambda operator: operator.staking_module.id == module.id, node_operators)))

            last_ejected_validators = self.w3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices(
                module.id,
                node_operators_ids_in_module,
            ).call()

            for no_id, validator_index in zip(node_operators_ids_in_module, last_ejected_validators):
                result[(module.id, no_id)] = validator_index

        return result

    def get_lido_new_exited_validators(self, blockstamp: BlockStamp) -> dict[NodeOperatorIndex, int]:
        lido_validators = self._get_exited_lido_validators(blockstamp)
        node_operators = self.w3.lido_validators.get_lido_node_operators(blockstamp)

        for operator in node_operators:
            # If amount of exited validators weren't changed skip report for operator
            if lido_validators[(operator.staking_module.id, operator.id)] == operator.total_exited_validators:
                del lido_validators[(operator.staking_module.id, operator.id)]

        logger.info({'msg': 'Fetch new lido exited validators by node operator.', 'value': lido_validators})
        return lido_validators

    def _get_exited_lido_validators(self, blockstamp: BlockStamp) -> dict[NodeOperatorIndex, int]:
        lido_validators = self.w3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

        def exit_filter(validator: LidoValidator) -> int:
            # Returns 1 if True else 0
            return int(int(validator.validator.validator.exit_epoch) < blockstamp.ref_epoch)

        result = {}

        for index, validators in lido_validators.items():
            result[index] = reduce(lambda total, validator: total + exit_filter(validator), lido_validators[index], 0)

        return result

    def _get_oracle_report_limits(self, blockstamp: BlockStamp) -> OracleReportLimits:
        result = self.w3.lido_contracts.oracle_report_sanity_checker.functions.getOracleReportLimits().call(
            block_identifier=blockstamp.block_hash,
        )
        orl = named_tuple_to_dataclass(result, OracleReportLimits)
        logger.info({'msg': 'Fetch oracle sanity checks.', 'value': orl})
        return orl
