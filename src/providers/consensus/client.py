from functools import lru_cache
from typing import Literal, Optional, Union

from src.metrics.logging import logging
from src.metrics.prometheus.basic import CL_REQUESTS_DURATION
from src.providers.consensus.typings import (
    BlockDetailsResponse,
    BlockHeaderFullResponse,
    BlockHeaderResponseData,
    BlockRootResponse,
    Validator,
    BeaconSpecResponse,
    GenesisResponse,
)
from src.providers.http_provider import HTTPProvider, NotOkResponse
from src.typings import BlockRoot, BlockStamp, SlotNumber
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
    PROMETHEUS_HISTOGRAM = CL_REQUESTS_DURATION

    API_GET_BLOCK_ROOT = 'eth/v1/beacon/blocks/{}/root'
    API_GET_BLOCK_HEADER = 'eth/v1/beacon/headers/{}'
    API_GET_BLOCK_DETAILS = 'eth/v2/beacon/blocks/{}'
    API_GET_VALIDATORS = 'eth/v1/beacon/states/{}/validators'
    API_GET_SPEC = 'eth/v1/config/spec'
    API_GET_GENESIS = 'eth/v1/beacon/genesis'

    def get_config_spec(self):
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Config/getSpec
        """
        data, _ = self._get(self.API_GET_SPEC)
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getSpec")
        return BeaconSpecResponse.from_response(**data)

    def get_genesis(self):
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getGenesis
        """
        data, _ = self._get('eth/v1/beacon/genesis')
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getGenesis")
        return GenesisResponse.from_response(**data)

    def get_block_root(self, state_id: Union[SlotNumber, BlockRoot, LiteralState]) -> BlockRootResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot

        No cache because this method is using to get finalized and head block, and they could not be cached by args.
        """
        data, _ = self._get(self.API_GET_BLOCK_ROOT, (state_id,))
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockRoot")
        return BlockRootResponse.from_response(**data)

    @lru_cache(maxsize=1)
    def get_block_header(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockHeaderFullResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader
        """
        data, meta_data = self._get(self.API_GET_BLOCK_HEADER, (state_id,))
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockHeader")
        resp = BlockHeaderFullResponse.from_response(data=BlockHeaderResponseData.from_response(**data), **meta_data)
        return resp

    @lru_cache(maxsize=1)
    def get_block_details(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(self.API_GET_BLOCK_DETAILS, (state_id,))
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockV2")
        return BlockDetailsResponse.from_response(**data)

    @lru_cache(maxsize=1)
    def get_validators(self, blockstamp: BlockStamp) -> list[Validator]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        return self.get_validators_no_cache(blockstamp)

    @list_of_dataclasses(Validator.from_response)
    def get_validators_no_cache(self, blockstamp: BlockStamp, pub_keys: Optional[str | tuple] = None) -> list[dict]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        try:
            data, _ = self._get(self.API_GET_VALIDATORS, (blockstamp.state_root,), query_params={'id': pub_keys})
            if not isinstance(data, list):
                raise ValueError("Expected list response from getStateValidators")
            return data
        except NotOkResponse as error:
            # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
            # Trying to get validators by slot number
            if 'State not found: state not found in the last' in error.text:
                data, _ = self._get(self.API_GET_VALIDATORS, (blockstamp.slot_number,), query_params={'id': pub_keys})
                if not isinstance(data, list):
                    raise ValueError("Expected list response from getStateValidators")  # pylint: disable=raise-missing-from
                return data
            raise error from error
