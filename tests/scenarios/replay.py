"""Typed oracle-client adapters backed exclusively by a scenario cassette."""

from typing import cast

from src.providers.consensus.types import (
    BeaconSpecResponse,
    BeaconStateView,
    BlockDetailsResponse,
    BlockHeaderFullResponse,
    BlockHeaderResponseData,
    GenesisResponse,
    PendingConsolidation,
    PendingDeposit,
    Validator,
)
from src.providers.http_provider import NotOkResponse
from src.providers.keys.types import LidoKey
from src.types import BlockRoot, BlockStamp, EpochNumber, SlotNumber, StateRoot
from tests.scenarios.cassette import Cassette, JsonValue


class CassetteConsensusClient:
    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette

    def get_config_spec(self) -> BeaconSpecResponse:
        return BeaconSpecResponse.from_response(**_response_data(self.cassette.replay('consensus', 'get_config_spec')))

    def is_gloas_epoch(self, epoch: EpochNumber) -> bool:
        return epoch >= self.get_config_spec().GLOAS_FORK_EPOCH

    def is_gloas_slot(self, slot: SlotNumber) -> bool:
        spec = self.get_config_spec()
        return self.is_gloas_epoch(EpochNumber(slot // spec.SLOTS_PER_EPOCH))

    def get_genesis(self) -> GenesisResponse:
        return GenesisResponse.from_response(**_response_data(self.cassette.replay('consensus', 'get_genesis')))

    def get_block_header(self, state_id: SlotNumber | BlockRoot) -> BlockHeaderFullResponse:
        response = _response_object(self.cassette.replay('consensus', 'get_block_header', {'state_id': str(state_id)}))
        if response.get('cassette_http_status') == 404:
            raise NotOkResponse('recorded missed slot', status=404, text='Not Found')
        data = _dict_value(response, 'data')
        return BlockHeaderFullResponse.from_response(
            data=BlockHeaderResponseData.from_response(**data),
            execution_optimistic=response.get('execution_optimistic', False),
            finalized=response.get('finalized'),
        )

    def get_block_details(self, state_id: SlotNumber | BlockRoot) -> BlockDetailsResponse:
        response = self.cassette.replay('consensus', 'get_block_details', {'state_id': str(state_id)})
        return BlockDetailsResponse.from_response(**_response_data(response))

    def get_state_view(self, state_identifier: BlockStamp | tuple[StateRoot, SlotNumber]) -> BeaconStateView:
        if isinstance(state_identifier, BlockStamp):
            state_root, slot_number = state_identifier.state_root, state_identifier.slot_number
        else:
            state_root, slot_number = state_identifier
        response = self.cassette.replay(
            'consensus',
            'get_state_view',
            {'state_root': str(state_root), 'slot_number': int(slot_number)},
        )
        return BeaconStateView.from_response(**_response_data(response))

    def get_state_view_no_cache(self, state_identifier: BlockStamp | tuple[StateRoot, SlotNumber]) -> BeaconStateView:
        # A cassette is a fixed recording, so there is no cache to bypass. The bunker's CL-rebase
        # sampling calls this to force a fresh read per state root; replaying the same recorded
        # response is the faithful equivalent.
        return self.get_state_view(state_identifier)

    def get_validators(self, blockstamp: BlockStamp) -> list[Validator]:
        return self.get_state_view(blockstamp).indexed_validators

    def get_validators_no_cache(self, blockstamp: BlockStamp) -> list[Validator]:
        return self.get_state_view(blockstamp).indexed_validators

    def get_validators_by_indexes(self, blockstamp: BlockStamp) -> dict[int, Validator]:
        return {validator.index: validator for validator in self.get_validators(blockstamp)}

    def get_pending_deposits(self, blockstamp: BlockStamp) -> list[PendingDeposit]:
        child_state_root = getattr(blockstamp, 'child_state_root', None)
        child_slot = getattr(blockstamp, 'child_slot', None)
        if child_state_root is not None and child_slot is not None:
            return self.get_state_view((child_state_root, child_slot)).pending_deposits
        return self.get_state_view(blockstamp).pending_deposits

    def get_pending_consolidations(self, blockstamp: BlockStamp) -> list[PendingConsolidation]:
        return self.get_state_view(blockstamp).pending_consolidations


class CassetteKeysAPIClient:
    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette

    def get_used_lido_keys(self, _blockstamp: BlockStamp) -> list[LidoKey]:
        response = _response_object(self.cassette.replay('keys_api', 'get_used_lido_keys'))
        data = response.get('data')
        if not isinstance(data, list):
            raise ValueError('recorded Keys API response data must be a list')
        return [LidoKey.from_response(**cast(dict, item)) for item in data]


def _response_data(value: JsonValue) -> dict[str, JsonValue]:
    return _dict_value(_response_object(value), 'data')


def _response_object(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError('recorded provider response must be a JSON object')
    return value


def _dict_value(value: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f'recorded provider response field {key!r} must be a JSON object')
    return item
