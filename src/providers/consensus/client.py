from functools import lru_cache
from typing import Optional, List, Union

from src.metrics.logging import logging
from src.metrics.prometheus.basic import ETH2_REQUESTS_DURATION, ETH2_REQUESTS
from src.providers.consensus.typings import BlockRootResponse, BlockDetailsResponse, Validator
from src.providers.http_provider import HTTPProvider
from src.typings import SlotNumber, StateRoot, BlockRoot
from src.utils.freeze_decorator import freezeargs

logger = logging.getLogger(__name__)


class ConsensusClient(HTTPProvider):
    """
    API specifications can be found here
    https://ethereum.github.io/beacon-APIs/

    state_id
    State identifier. Can be one of: "head" (canonical head in node's view), "genesis", "finalized", "justified", <slot>, <hex encoded stateRoot with 0x prefix>.
    """
    PROMETHEUS_COUNTER = ETH2_REQUESTS
    PROMETHEUS_HISTOGRAM = ETH2_REQUESTS_DURATION

    API_GET_BLOCK_ROOT = 'eth/v1/beacon/blocks/{}/root'
    API_GET_BLOCK_DETAILS = 'eth/v2/beacon/blocks/{}'
    API_GET_VALIDATORS = 'eth/v1/beacon/states/{}/validators'

    @freezeargs
    @lru_cache(maxsize=1)
    def get_block_root(self, state_id: Union[str, SlotNumber, BlockRoot]) -> BlockRootResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot"""
        data, _ = self._get(self.API_GET_BLOCK_ROOT.format(state_id))
        return data

    @freezeargs
    @lru_cache(maxsize=1)
    def get_block_details(self, state_id: Union[str, SlotNumber, BlockRoot]) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(self.API_GET_BLOCK_DETAILS.format(state_id))
        return data

    @freezeargs
    @lru_cache(maxsize=1)
    def get_validators(self, state_id: Union[str, SlotNumber, StateRoot], pub_keys: Optional[str] = None) -> List[Validator]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        data, _ = self._get(self.API_GET_VALIDATORS.format(state_id), params={'id': pub_keys})
        return data
