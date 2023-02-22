from functools import lru_cache
from typing import Optional, Union

from src.metrics.logging import logging
from src.metrics.prometheus.basic import ETH2_REQUESTS_DURATION, ETH2_REQUESTS
from src.providers.consensus.typings import BlockRootResponse, BlockDetailsResponse, Validator, BlockHeaderFullResponse, \
    BlockHeaderResponseData
from src.providers.http_provider import HTTPProvider
from src.typings import SlotNumber, StateRoot, BlockRoot
from src.utils.dataclass import list_of_dataclasses


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
    API_GET_BLOCK_HEADER = '/eth/v1/beacon/headers/{}'
    API_GET_BLOCK_DETAILS = 'eth/v2/beacon/blocks/{}'
    API_GET_VALIDATORS = 'eth/v1/beacon/states/{}/validators'

    NON_CACHEABLE_STATES = ('head', 'finalized', 'justified')

    def get_block_root(self, state_id: Union[str, SlotNumber, BlockRoot]) -> BlockRootResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot

        No cache because this method is using to get finalized and head block, and they could not be cached by args.
        """
        data, _ = self._get(self.API_GET_BLOCK_ROOT.format(state_id))
        return BlockRootResponse(**data)

    def get_block_header(self, state_id: Union[str, SlotNumber, BlockRoot]) -> BlockHeaderFullResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot

        No cache because this method is using to get finalized and head block, and they could not be cached by args.
        """
        data, rest_response = self._get(self.API_GET_BLOCK_HEADER.format(state_id))
        resp = BlockHeaderFullResponse(data=BlockHeaderResponseData(**data), **rest_response)
        if not resp.finalized:
            raise Exception(f'Slot [{state_id}] is not finalized')
        if not resp.data.canonical:
            raise Exception(f'Slot [{state_id}] is not canonical')
        return resp

    @lru_cache(maxsize=1)
    def get_block_details(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        if state_id in self.NON_CACHEABLE_STATES:
            raise ValueError(f'Block details for state_id: {state_id} could not be cached. '
                             'Please provide slot number or block root.')
        data, _ = self._get(self.API_GET_BLOCK_DETAILS.format(state_id))
        return BlockDetailsResponse(**data)

    # We need to store all validators from different slots for bunker mode.
    # ToDo optimize RAM usage
    @lru_cache(maxsize=5)
    @list_of_dataclasses(Validator)
    def get_validators(self, state_id: Union[SlotNumber, StateRoot], pub_keys: Optional[str] = None) -> list[Validator]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        if state_id in self.NON_CACHEABLE_STATES:
            raise ValueError(f'Validators for state_id: {state_id} could not be cached. '
                             'Please provide slot number or state root.')
        data, _ = self._get(self.API_GET_VALIDATORS.format(state_id), params={'id': pub_keys})
        return data
