import logging
from functools import lru_cache

from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class OracleDaemonConfigContract(ContractInterface):
    abi_path = './assets/OracleDaemonConfig.json'

    @lru_cache(maxsize=1)
    def normalized_cl_reward_per_epoch(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('NORMALIZED_CL_REWARD_PER_EPOCH').call(block_identifier=block_identifier)

        response = Web3.to_int(response)
        logger.info({
            'msg': 'Call `NORMALIZED_CL_REWARD_PER_EPOCH()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def normalized_cl_reward_mistake_rate_bp(self, block_identifier: BlockIdentifier = 'latest') -> float:
        response = self.functions.get('NORMALIZED_CL_REWARD_MISTAKE_RATE_BP').call(block_identifier=block_identifier)

        response = Web3.to_int(response)
        logger.info({
            'msg': 'Call `NORMALIZED_CL_REWARD_MISTAKE_RATE_BP()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def rebase_check_nearest_epoch_distance(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('REBASE_CHECK_NEAREST_EPOCH_DISTANCE').call(block_identifier=block_identifier)

        response = Web3.to_int(response)
        logger.info({
            'msg': 'Call `REBASE_CHECK_NEAREST_EPOCH_DISTANCE()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def rebase_check_distant_epoch_distance(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('REBASE_CHECK_DISTANT_EPOCH_DISTANCE').call(block_identifier=block_identifier)

        response = Web3.to_int(response)
        logger.info({
            'msg': 'Call `REBASE_CHECK_DISTANT_EPOCH_DISTANCE()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def node_operator_network_penetration_threshold_bp(self, block_identifier: BlockIdentifier = 'latest') -> float:
        response = self.functions.get('NODE_OPERATOR_NETWORK_PENETRATION_THRESHOLD_BP').call(block_identifier=block_identifier)

        response = Web3.to_int(response)
        logger.info({
            'msg': 'Call `NODE_OPERATOR_NETWORK_PENETRATION_THRESHOLD_BP()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def prediction_duration_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('PREDICTION_DURATION_IN_SLOTS').call(block_identifier=block_identifier)

        response = Web3.to_int(response)
        logger.info({
            'msg': 'Call `PREDICTION_DURATION_IN_SLOTS()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def finalization_max_negative_rebase_epoch_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('FINALIZATION_MAX_NEGATIVE_REBASE_EPOCH_SHIFT').call(block_identifier=block_identifier)

        response = Web3.to_int(primitive=response)

        logger.info({
            'msg': 'Call `FINALIZATION_MAX_NEGATIVE_REBASE_EPOCH_SHIFT()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def validator_delayed_timeout_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS').call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def validator_delinquent_timeout_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self.functions.get('VALIDATOR_DELINQUENT_TIMEOUT_IN_SLOTS').call(block_identifier=block_identifier)

        logger.info({
            'msg': 'Call `VALIDATOR_DELINQUENT_TIMEOUT_IN_SLOTS()`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response
