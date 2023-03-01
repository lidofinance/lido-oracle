from functools import lru_cache
from typing import Optional, Union, Literal

from src.metrics.logging import logging
from src.metrics.prometheus.basic import ETH2_REQUESTS_DURATION, ETH2_REQUESTS
from src.providers.consensus.typings import (
    BlockRootResponse,
    BlockDetailsResponse,
    Validator,
    BlockHeaderFullResponse,
    BlockHeaderResponseData,
)
from src.providers.http_provider import HTTPProvider, NotOkResponse
from src.typings import SlotNumber, BlockRoot, BlockStamp
from src.utils.dataclass import list_of_dataclasses


logger = logging.getLogger(__name__)


LiteralState = Literal['head', 'genesis', 'finalized', 'justified']


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

    def get_block_root(self, state_id: Union[SlotNumber, BlockRoot, LiteralState]) -> BlockRootResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot

        No cache because this method is using to get finalized and head block, and they could not be cached by args.
        """
        data, _ = self._get(self.API_GET_BLOCK_ROOT.format(state_id))
        return BlockRootResponse(**data)

    @lru_cache(maxsize=1)
    def get_block_header(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockHeaderFullResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
        """
        data, meta_data = self._get(self.API_GET_BLOCK_HEADER.format(state_id))
        resp = BlockHeaderFullResponse(data=BlockHeaderResponseData(**data), **meta_data)
        return resp

    @lru_cache(maxsize=1)
    def get_block_details(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(self.API_GET_BLOCK_DETAILS.format(state_id))
        return BlockDetailsResponse(**data)

    @lru_cache(maxsize=1)
    def get_validators(self, blockstamp: BlockStamp, pub_keys: Optional[str | tuple] = None) -> list[Validator]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        return self.get_validators_no_cache(blockstamp, pub_keys)

    @list_of_dataclasses(Validator)
    def get_validators_no_cache(self, blockstamp: BlockStamp, pub_keys: Optional[str | tuple] = None) -> list[Validator]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        try:
            data, _ = self._get(self.API_GET_VALIDATORS.format(blockstamp.state_root), params={'id': pub_keys})
            return data
        except NotOkResponse as error:
            # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
            # Trying to get validators by slot number
            if 'State not found: state not found in the last' in error.text:
                data, _ = self._get(self.API_GET_VALIDATORS.format(blockstamp.slot_number), params={'id': pub_keys})
                return data
            raise error from error
