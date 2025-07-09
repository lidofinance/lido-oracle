import logging

from src.utils.cache import global_lru_cache as lru_cache

from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface


logger = logging.getLogger(__name__)


class OracleDaemonConfigContract(ContractInterface):
    abi_path = './assets/OracleDaemonConfig.json'

    def _get(self, param: str, block_identifier: BlockIdentifier = 'latest') -> int:
        response = Web3.to_int(self.functions.get(param).call(block_identifier=block_identifier))

        logger.info({
            'msg': f'Call `get({param})`.',
            'value': response,
            'block_identifier': repr(block_identifier),
            'to': self.address,
        })
        return response

    @lru_cache(maxsize=1)
    def normalized_cl_reward_per_epoch(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('NORMALIZED_CL_REWARD_PER_EPOCH', block_identifier)

    @lru_cache(maxsize=1)
    def normalized_cl_reward_mistake_rate_bp(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('NORMALIZED_CL_REWARD_MISTAKE_RATE_BP', block_identifier)

    @lru_cache(maxsize=1)
    def rebase_check_nearest_epoch_distance(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('REBASE_CHECK_NEAREST_EPOCH_DISTANCE', block_identifier)

    @lru_cache(maxsize=1)
    def rebase_check_distant_epoch_distance(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('REBASE_CHECK_DISTANT_EPOCH_DISTANCE', block_identifier)

    @lru_cache(maxsize=1)
    def prediction_duration_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('PREDICTION_DURATION_IN_SLOTS', block_identifier)

    @lru_cache(maxsize=1)
    def finalization_max_negative_rebase_epoch_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('FINALIZATION_MAX_NEGATIVE_REBASE_EPOCH_SHIFT', block_identifier)

    @lru_cache(maxsize=1)
    def exit_events_lookback_window_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('EXIT_EVENTS_LOOKBACK_WINDOW_IN_SLOTS', block_identifier)

    @lru_cache(maxsize=1)
    def slashing_reserve_we_left_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('SLASHING_RESERVE_WE_LEFT_SHIFT', block_identifier)

    @lru_cache(maxsize=1)
    def slashing_reserve_we_right_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('SLASHING_RESERVE_WE_RIGHT_SHIFT', block_identifier)
