from http import HTTPStatus
from typing import Literal, cast

from json_stream.base import TransientStreamingJSONObject  # type: ignore

from src.metrics.logging import logging
from src.metrics.prometheus.basic import CL_REQUESTS_DURATION
from src.providers.consensus.types import (
    BlockDetailsResponse,
    BlockHeaderFullResponse,
    BlockHeaderResponseData,
    BlockRootResponse,
    Validator,
    BeaconSpecResponse,
    GenesisResponse,
    SlotAttestationCommittee, BlockAttestation,
)
from src.providers.http_provider import HTTPProvider, NotOkResponse
from src.types import BlockRoot, BlockStamp, SlotNumber, EpochNumber
from src.utils.dataclass import list_of_dataclasses
from src.utils.cache import global_lru_cache as lru_cache

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
    API_GET_BLOCK_ATTESTATIONS = 'eth/v1/beacon/blocks/{}/attestations'
    API_GET_ATTESTATION_COMMITTEES = 'eth/v1/beacon/states/{}/committees'
    API_GET_STATE = 'eth/v2/debug/beacon/states/{}'
    API_GET_VALIDATORS = 'eth/v1/beacon/states/{}/validators'
    API_GET_SPEC = 'eth/v1/config/spec'
    API_GET_GENESIS = 'eth/v1/beacon/genesis'

    def get_config_spec(self):
        """Spec: https://ethereum.github.io/beacon-APIs/#/Config/getSpec"""
        data, _ = self._get(self.API_GET_SPEC)
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getSpec")
        return BeaconSpecResponse.from_response(**data)

    def get_genesis(self):
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getGenesis
        """
        data, _ = self._get(self.API_GET_GENESIS)
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getGenesis")
        return GenesisResponse.from_response(**data)

    def get_block_root(self, state_id: SlotNumber | BlockRoot | LiteralState) -> BlockRootResponse:
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockRoot

        There is no cache because this method is used to get finalized and head blocks.
        """
        data, _ = self._get(
            self.API_GET_BLOCK_ROOT,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
        )
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockRoot")
        return BlockRootResponse.from_response(**data)

    @lru_cache(maxsize=1)
    def get_block_header(self, state_id: SlotNumber | BlockRoot) -> BlockHeaderFullResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader"""
        data, meta_data = cast(tuple[dict, dict], self._get(
            self.API_GET_BLOCK_HEADER,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
        ))
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockHeader")
        resp = BlockHeaderFullResponse.from_response(data=BlockHeaderResponseData.from_response(**data), **meta_data)
        return resp

    @lru_cache(maxsize=1)
    def get_block_details(self, state_id: SlotNumber | BlockRoot) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(
            self.API_GET_BLOCK_DETAILS,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
        )
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getBlockV2")
        return BlockDetailsResponse.from_response(**data)

    @lru_cache(maxsize=256)
    def get_block_attestations(self, state_id: SlotNumber | BlockRoot) -> list[BlockAttestation]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockAttestations"""
        data, _ = self._get(
            self.API_GET_BLOCK_ATTESTATIONS,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
        )
        if not isinstance(data, list):
            raise ValueError("Expected list response from getBlockAttestations")
        return [BlockAttestation.from_response(**att) for att in data]

    @list_of_dataclasses(SlotAttestationCommittee.from_response)
    def get_attestation_committees(
        self,
        blockstamp: BlockStamp,
        epoch: EpochNumber | None = None,
        index: int | None = None,
        slot: SlotNumber | None = None
    ) -> list[SlotAttestationCommittee]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getEpochCommittees"""
        try:
            data, _ = self._get(
                self.API_GET_ATTESTATION_COMMITTEES,
                path_params=(blockstamp.state_root,),
                query_params={'epoch': epoch, 'index': index, 'slot': slot},
                force_raise=self.__raise_on_prysm_error
            )
        except NotOkResponse as error:
            if self.PRYSM_STATE_NOT_FOUND_ERROR in error.text:
                data = self._get_attestation_committees_with_prysm(blockstamp, epoch, index, slot)
            else:
                raise error
        return data

    @lru_cache(maxsize=1)
    def get_state_block_roots(self, state_id: SlotNumber) -> list[BlockRoot]:
        streamed_json = cast(TransientStreamingJSONObject, self._get(
                self.API_GET_STATE,
                path_params=(state_id,),
                stream=True,
            ))
        return list(streamed_json['data']['block_roots'])

    @lru_cache(maxsize=1)
    def get_validators(self, blockstamp: BlockStamp) -> list[Validator]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        return self.get_validators_no_cache(blockstamp)

    @list_of_dataclasses(Validator.from_response)
    def get_validators_no_cache(self, blockstamp: BlockStamp, pub_keys: str | tuple | None = None) -> list[dict]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidators"""
        try:
            data, _ = self._get(
                self.API_GET_VALIDATORS,
                path_params=(blockstamp.state_root,),
                query_params={'id': pub_keys},
                force_raise=self.__raise_on_prysm_error
            )
            if not isinstance(data, list):
                raise ValueError("Expected list response from getStateValidators")
            return data
        except NotOkResponse as error:
            if self.PRYSM_STATE_NOT_FOUND_ERROR in error.text:
                return self._get_validators_with_prysm(blockstamp, pub_keys)

            raise error

    PRYSM_STATE_NOT_FOUND_ERROR = 'State not found: state not found in the last'

    def __raise_on_prysm_error(self, errors: list[Exception]) -> Exception | None:
        """
        Prysm can't return validators by state root if it is old enough, but it can return them via slot number.

        raise error immediately if this is prysm specific exception
        """
        last_error = errors[-1]
        if isinstance(last_error, NotOkResponse) and self.PRYSM_STATE_NOT_FOUND_ERROR in last_error.text:
            return last_error
        return None

    def _get_attestation_committees_with_prysm(
        self,
        blockstamp: BlockStamp,
        epoch: EpochNumber | None = None,
        index: int | None = None,
        slot: SlotNumber | None = None
    ) -> list[dict]:
        # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
        # Trying to get committees by slot number
        data, _ = self._get(
            self.API_GET_ATTESTATION_COMMITTEES,
            path_params=(blockstamp.slot_number,),
            query_params={'epoch': epoch, 'index': index, 'slot': slot},
        )
        if not isinstance(data, list):
            raise ValueError("Expected list response from getEpochCommittees")
        return data

    def _get_validators_with_prysm(self, blockstamp: BlockStamp, pub_keys: str | tuple | None = None) -> list[dict]:
        # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
        # Trying to get validators by slot number
        data, _ = self._get(
            self.API_GET_VALIDATORS,
            path_params=(blockstamp.slot_number,),
            query_params={'id': pub_keys}
        )
        if not isinstance(data, list):
            raise ValueError("Expected list response from getStateValidators")
        return data

    def __raise_last_missed_slot_error(self, errors: list[Exception]) -> Exception | None:
        """
        Prioritize NotOkResponse before other exceptions (ConnectionError, TimeoutError).
        If status is 404 slot is missed and this should be handled correctly.
        """
        if len(errors) == len(self.hosts):
            for error in errors:
                if isinstance(error, NotOkResponse) and error.status == HTTPStatus.NOT_FOUND:
                    return error

        return None

    def _get_chain_id_with_provider(self, provider_index: int) -> int:
        data, _ = self._get_without_fallbacks(self.hosts[provider_index], self.API_GET_SPEC)
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getSpec")
        return int(BeaconSpecResponse.from_response(**data).DEPOSIT_CHAIN_ID)
