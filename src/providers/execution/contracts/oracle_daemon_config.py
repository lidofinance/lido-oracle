import logging

from web3 import Web3
from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.utils.cache import global_lru_cache as lru_cache


logger = logging.getLogger(__name__)


class OracleDaemonConfigContract(ContractInterface):
    abi_path = './assets/OracleDaemonConfig.json'

    def _get(self, param: str, block_identifier: BlockIdentifier = 'latest') -> int:
        response = Web3.to_int(self.functions.get(param).call(block_identifier=block_identifier))

        logger.info(
            {
                'msg': f'Call `get({param})`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    @lru_cache(maxsize=1)
    def bunker_finalization_delay_epochs(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('BUNKER_FINALIZATION_DELAY_EPOCHS', block_identifier)

    @lru_cache(maxsize=1)
    def bunker_base_slashing_impact_rate_ppm(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('BUNKER_BASE_SLASHING_IMPACT_RATE_PPM', block_identifier)

    @lru_cache(maxsize=1)
    def bunker_slashing_impact_threshold_ppm(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('BUNKER_SLASHING_IMPACT_THRESHOLD_PPM', block_identifier)

    @lru_cache(maxsize=1)
    def prediction_duration_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('PREDICTION_DURATION_IN_SLOTS', block_identifier)

    @lru_cache(maxsize=1)
    def exit_events_lookback_window_in_slots(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('EXIT_EVENTS_LOOKBACK_WINDOW_IN_SLOTS', block_identifier)

    @lru_cache(maxsize=1)
    def slashing_reserve_we_left_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('SLASHING_RESERVE_WE_LEFT_SHIFT', block_identifier)

    @lru_cache(maxsize=1)
    def slashing_reserve_we_right_shift(self, block_identifier: BlockIdentifier = 'latest') -> int:
        return self._get('SLASHING_RESERVE_WE_RIGHT_SHIFT', block_identifier)
