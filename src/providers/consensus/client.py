from http import HTTPStatus
from typing import Any, Literal, cast

from src import variables
from src.metrics.logging import logging
from src.metrics.prometheus.basic import CL_REQUESTS_DURATION
from src.providers.consensus.types import (
    BeaconSpecResponse,
    BeaconStateView,
    BlockAttestation,
    BlockAttestationResponse,
    BlockDetailsResponse,
    BlockHeaderFullResponse,
    BlockHeaderResponseData,
    BlockRootResponse,
    GenesisResponse,
    PendingDeposit,
    ProposerDuties,
    SlotAttestationCommittee,
    SyncAggregate,
    SyncCommittee,
    Validator,
)
from src.providers.http_provider import (
    HTTPProvider,
    NotOkResponse,
    data_is_dict,
    data_is_list,
    data_is_transient_dict,
)
from src.types import BlockRoot, BlockStamp, EpochNumber, SlotNumber, StateRoot
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.dataclass import list_of_dataclasses

logger = logging.getLogger(__name__)

LiteralState = Literal['head', 'genesis', 'finalized', 'justified']


class ConsensusClientError(NotOkResponse):
    pass


class ConsensusClient(HTTPProvider):
    """
    API specifications can be found here
    https://ethereum.github.io/beacon-APIs/

    state_id
    State identifier. Can be one of: "head" (canonical head in node's view), "genesis", "finalized", "justified", <slot>, <hex encoded stateRoot with 0x prefix>.
    """

    PROVIDER_EXCEPTION = ConsensusClientError
    PROMETHEUS_HISTOGRAM = CL_REQUESTS_DURATION

    API_GET_BLOCK_ROOT = 'eth/v1/beacon/blocks/{}/root'
    API_GET_BLOCK_HEADER = 'eth/v1/beacon/headers/{}'
    API_GET_BLOCK_DETAILS = 'eth/v2/beacon/blocks/{}'
    API_GET_ATTESTATION_COMMITTEES = 'eth/v1/beacon/states/{}/committees'
    API_GET_SYNC_COMMITTEE = 'eth/v1/beacon/states/{}/sync_committees'
    API_GET_PROPOSER_DUTIES = 'eth/v1/validator/duties/proposer/{}'
    API_GET_STATE = 'eth/v2/debug/beacon/states/{}'
    API_GET_SPEC = 'eth/v1/config/spec'
    API_GET_GENESIS = 'eth/v1/beacon/genesis'
    API_GET_VALIDATOR = 'eth/v1/beacon/states/{}/validators/{}'

    def get_config_spec(self) -> BeaconSpecResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Config/getSpec"""
        data, _ = self._get(self.API_GET_SPEC, retval_validator=data_is_dict)
        return BeaconSpecResponse.from_response(**data)

    def get_genesis(self):
        """
        Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getGenesis
        """
        data, _ = self._get(self.API_GET_GENESIS, retval_validator=data_is_dict)
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
            retval_validator=data_is_dict,
        )
        return BlockRootResponse.from_response(**data)

    @lru_cache(maxsize=1)
    def get_block_header(self, state_id: SlotNumber | BlockRoot) -> BlockHeaderFullResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockHeader"""
        data, meta_data = self._get(
            self.API_GET_BLOCK_HEADER,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
            retval_validator=data_is_dict,
        )
        resp = BlockHeaderFullResponse.from_response(data=BlockHeaderResponseData.from_response(**data), **meta_data)
        return resp

    @lru_cache(maxsize=1)
    def get_block_details(self, state_id: SlotNumber | BlockRoot) -> BlockDetailsResponse:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(
            self.API_GET_BLOCK_DETAILS,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
            retval_validator=data_is_dict,
        )
        return BlockDetailsResponse.from_response(**data)

    @lru_cache(maxsize=variables.CSM_ORACLE_MAX_CONCURRENCY * 32 * 2)  # threads count * blocks * epochs to check duties
    def get_block_attestations_and_sync(
        self, state_id: SlotNumber | BlockRoot
    ) -> tuple[list[BlockAttestation], SyncAggregate]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getBlockV2"""
        data, _ = self._get(
            self.API_GET_BLOCK_DETAILS,
            path_params=(state_id,),
            force_raise=self.__raise_last_missed_slot_error,
            retval_validator=data_is_dict,
        )

        attestations = [
            cast(BlockAttestation, BlockAttestationResponse.from_response(**att))
            for att in data["message"]["body"]["attestations"]
        ]
        sync = SyncAggregate.from_response(**data["message"]["body"]["sync_aggregate"])

        return attestations, sync

    @list_of_dataclasses(SlotAttestationCommittee.from_response)
    def get_attestation_committees(
        self,
        blockstamp: BlockStamp,
        epoch: EpochNumber | None = None,
        committee_index: int | None = None,
        slot: SlotNumber | None = None,
    ) -> list[SlotAttestationCommittee]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getEpochCommittees"""
        try:
            data, _ = self._get(
                self.API_GET_ATTESTATION_COMMITTEES,
                path_params=(blockstamp.state_root,),
                query_params={'epoch': epoch, 'index': committee_index, 'slot': slot},
                force_raise=self.__raise_on_prysm_error,
                retval_validator=data_is_list,
            )
        except NotOkResponse as error:
            if self.PRYSM_STATE_NOT_FOUND_ERROR in error.text:
                data = self._get_attestation_committees_with_prysm(
                    blockstamp,
                    epoch,
                    committee_index,
                    slot,
                )
            else:
                raise error
        return cast(list[SlotAttestationCommittee], data)

    def get_sync_committee(self, blockstamp: BlockStamp, epoch: EpochNumber) -> SyncCommittee:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getEpochSyncCommittees"""
        try:
            data, _ = self._get(
                self.API_GET_SYNC_COMMITTEE,
                path_params=(blockstamp.state_root,),
                query_params={'epoch': epoch},
                force_raise=self.__raise_on_prysm_error,
                retval_validator=data_is_dict,
            )
        except NotOkResponse as error:
            if self.PRYSM_STATE_NOT_FOUND_ERROR in error.text:
                data = self._get_sync_committee_with_prysm(
                    blockstamp,
                    epoch,
                )
            else:
                raise error
        return SyncCommittee.from_response(**data)

    @list_of_dataclasses(ProposerDuties.from_response)
    def get_proposer_duties(self, epoch: EpochNumber, expected_dependent_root: BlockRoot) -> list[ProposerDuties]:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Validator/getProposerDuties"""

        def data_is_list_and_dependent_root_matches(data: Any, meta: dict, endpoint: str):
            data_is_list(data, meta, endpoint=endpoint)
            # It is recommended by spec to use the dependent root to ensure the epoch is correct
            if meta["dependent_root"] != expected_dependent_root:
                raise ValueError(
                    "Dependent root for proposer duties request mismatch: "
                    f"{meta['dependent_root']=} is not {expected_dependent_root=}. "
                    "Probably, CL node is not fully synced."
                )

        data, _ = self._get(
            self.API_GET_PROPOSER_DUTIES,
            path_params=(epoch,),
            retval_validator=data_is_list_and_dependent_root_matches,
        )
        return data

    @lru_cache(maxsize=1)
    def get_state_block_roots(self, state_id: SlotNumber) -> list[BlockRoot]:
        data, _ = self._get(
            self.API_GET_STATE,
            path_params=(state_id,),
            stream=True,
            retval_validator=data_is_transient_dict,
        )
        return list(data["block_roots"])

    def get_validators(self, blockstamp: BlockStamp) -> list[Validator]:
        return self.get_state_view(blockstamp).indexed_validators

    def get_validators_no_cache(self, blockstamp: BlockStamp) -> list[Validator]:
        return self.get_state_view_no_cache(blockstamp).indexed_validators

    PRYSM_STATE_NOT_FOUND_ERROR = 'State not found'

    @lru_cache(maxsize=1)
    def get_state_view(self, blockstamp: BlockStamp) -> BeaconStateView:
        return self.get_state_view_no_cache(blockstamp)

    def get_state_view_no_cache(self, blockstamp: BlockStamp) -> BeaconStateView:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Debug/getStateV2"""

        logger.info(
            {
                'msg': 'Getting state...',
                'url': self.API_GET_STATE,
                'slot_number': blockstamp.slot_number,
                'state_root': blockstamp.state_root,
            }
        )
        try:
            data = self._get_state_by_state_id(blockstamp.state_root)
        except NotOkResponse as error:
            # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
            if self.PRYSM_STATE_NOT_FOUND_ERROR in error.text:
                data = self._get_state_by_state_id(blockstamp.slot_number)
            else:
                raise

        return BeaconStateView.from_response(**data)

    def get_pending_deposits(self, blockstamp: BlockStamp) -> list[PendingDeposit]:
        return self.get_state_view(blockstamp).pending_deposits

    def get_validator_state(self, state_id: SlotNumber, validator_id: int) -> Validator:
        """Spec: https://ethereum.github.io/beacon-APIs/#/Beacon/getStateValidator"""
        data, _ = self._get(
            self.API_GET_VALIDATOR,
            path_params=(state_id, validator_id),
            force_raise=self.__raise_last_missed_slot_error,
        )
        if not isinstance(data, dict):
            raise ValueError("Expected mapping response from getStateValidator")
        return Validator.from_response(**data)

    def _get_state_by_state_id(self, state_id: StateRoot | SlotNumber) -> dict:
        data, _ = self._get(
            self.API_GET_STATE,
            path_params=(state_id,),
            force_raise=self.__raise_on_prysm_error,
            retval_validator=data_is_dict,
        )
        return data

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
        slot: SlotNumber | None = None,
    ) -> list[dict]:
        # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
        # Trying to get committees by slot number
        data, _ = self._get(
            self.API_GET_ATTESTATION_COMMITTEES,
            path_params=(blockstamp.slot_number,),
            query_params={'epoch': epoch, 'index': index, 'slot': slot},
            retval_validator=data_is_list,
        )
        return data

    def _get_sync_committee_with_prysm(
        self,
        blockstamp: BlockStamp,
        epoch: EpochNumber,
    ) -> list[dict]:
        # Avoid Prysm issue with state root - https://github.com/prysmaticlabs/prysm/issues/12053
        # Trying to get committees by slot number
        data, _ = self._get(
            self.API_GET_SYNC_COMMITTEE,
            path_params=(blockstamp.slot_number,),
            query_params={'epoch': epoch},
            retval_validator=data_is_dict,
        )
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
        data, _ = self._get_without_fallbacks(
            self.hosts[provider_index],
            self.API_GET_SPEC,
            retval_validator=data_is_dict,
        )
        return BeaconSpecResponse.from_response(**data).DEPOSIT_CHAIN_ID
