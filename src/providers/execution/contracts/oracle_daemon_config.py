import logging
from typing import Any

from src.utils.cache import global_lru_cache as lru_cache

from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class OracleDaemonConfigContract(ContractInterface):
    abi_path = './assets/OracleDaemonConfig.json'

    def _get(self, param: str, block_identifier: BlockIdentifier = 'latest') -> Any:
        response = self.functions.get(param).call(block_identifier=block_identifier)

        logger.info({
            'msg': f'Call `get({param})`.',
            'value': response,
            'block_identifier': repr(block_identifier),
        })
        return response

    @lru_cache(maxsize=1)
    def normalized_cl_reward_per_epoch(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('NORMALIZED_CL_REWARD_PER_EPOCH', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def normalized_cl_reward_mistake_rate_bp(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('NORMALIZED_CL_REWARD_MISTAKE_RATE_BP', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def rebase_check_nearest_epoch_distance(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('REBASE_CHECK_NEAREST_EPOCH_DISTANCE', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def rebase_check_distant_epoch_distance(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('REBASE_CHECK_DISTANT_EPOCH_DISTANCE', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def node_operator_network_penetration_threshold_bp(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('NODE_OPERATOR_NETWORK_PENETRATION_THRESHOLD_BP', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def prediction_duration_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('PREDICTION_DURATION_IN_SLOTS', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def finalization_max_negative_rebase_epoch_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('FINALIZATION_MAX_NEGATIVE_REBASE_EPOCH_SHIFT', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def validator_delayed_timeout_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('VALIDATOR_DELAYED_TIMEOUT_IN_SLOTS', block_identifier)
        return Web3.to_int(response)

    @lru_cache(maxsize=1)
    def validator_delinquent_timeout_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        response = self._get('VALIDATOR_DELINQUENT_TIMEOUT_IN_SLOTS', block_identifier)
        return Web3.to_int(response)