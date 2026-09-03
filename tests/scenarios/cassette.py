"""Versioned response cassettes shared by offline and fork scenario layers.

The format intentionally records logical client calls rather than raw HTTP exchanges. This keeps
replay independent of transport details while preserving the exact JSON response shape returned by
the CL, EL, or Keys API client.
"""

import copy
import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self


CASSETTE_SCHEMA_VERSION = 1

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type ProviderName = Literal['consensus', 'execution', 'keys_api']
type CassetteOrigin = Literal['recorded', 'synthetic']


@dataclass(frozen=True)
class CassetteManifest:
    schema_version: int
    scenario_id: str
    network: str
    module: str
    ref_slot: int
    recorded_at: str
    consensus_spec: dict[str, JsonValue]
    origin: CassetteOrigin
    base_scenario_id: str | None

    @classmethod
    def from_json(cls, value: JsonValue) -> Self:
        if not isinstance(value, dict):
            raise ValueError('cassette manifest must be a JSON object')

        schema_version = value.get('schema_version')
        if schema_version != CASSETTE_SCHEMA_VERSION:
            raise ValueError(
                f'unsupported cassette schema version {schema_version!r}; expected {CASSETTE_SCHEMA_VERSION}'
            )

        consensus_spec = value.get('consensus_spec')
        if not isinstance(consensus_spec, dict) or 'GLOAS_FORK_EPOCH' not in consensus_spec:
            raise ValueError('cassette manifest consensus_spec must include GLOAS_FORK_EPOCH')

        origin = value.get('origin', 'recorded')
        if origin not in ('recorded', 'synthetic'):
            raise ValueError(f'unsupported cassette origin {origin!r}')

        base_scenario_id = value.get('base_scenario_id')
        if base_scenario_id is not None and (not isinstance(base_scenario_id, str) or not base_scenario_id):
            raise ValueError('cassette manifest base_scenario_id must be a non-empty string')
        if origin == 'synthetic' and base_scenario_id is None:
            raise ValueError('synthetic cassette manifest must include base_scenario_id')

        return cls(
            schema_version=_required_int(value, 'schema_version'),
            scenario_id=_required_str(value, 'scenario_id'),
            network=_required_str(value, 'network'),
            module=_required_str(value, 'module'),
            ref_slot=_required_int(value, 'ref_slot'),
            recorded_at=_required_str(value, 'recorded_at'),
            consensus_spec=consensus_spec,
            origin=origin,
            base_scenario_id=base_scenario_id,
        )


@dataclass(frozen=True)
class CassetteEntry:
    provider: ProviderName
    method: str
    params: dict[str, JsonValue]
    response: JsonValue

    @classmethod
    def from_json(cls, value: JsonValue, directory: Path) -> Self:
        if not isinstance(value, dict):
            raise ValueError('cassette response entry must be a JSON object')

        provider = value.get('provider')
        if provider not in ('consensus', 'execution', 'keys_api'):
            raise ValueError(f'unsupported cassette provider {provider!r}')

        params = value.get('params', {})
        if not isinstance(params, dict):
            raise ValueError('cassette response params must be a JSON object')

        response_file = value.get('response_file')
        if response_file is not None:
            if not isinstance(response_file, str) or not response_file:
                raise ValueError('cassette response_file must be a non-empty string')
            response_path = (directory / response_file).resolve()
            if not response_path.is_relative_to(directory.resolve()):
                raise ValueError('cassette response_file must stay inside the cassette directory')
            response = _load_json(response_path)
        elif 'response' in value:
            response = value['response']
        else:
            raise ValueError('cassette response entry must contain response or response_file')

        return cls(
            provider=provider,
            method=_required_str(value, 'method'),
            params=params,
            response=response,
        )


class Cassette:
    """Load and replay one scenario's deterministic provider responses."""

    def __init__(self, manifest: CassetteManifest, entries: list[CassetteEntry]) -> None:
        self.manifest = manifest
        self._responses: dict[str, JsonValue] = {}
        for entry in entries:
            key = self._key(entry.provider, entry.method, entry.params)
            if key in self._responses:
                raise ValueError(
                    f'duplicate cassette response for provider={entry.provider!r}, method={entry.method!r}'
                )
            self._responses[key] = entry.response

    @classmethod
    def load(cls, directory: Path) -> Self:
        return cls._load(directory.resolve(), set())

    @classmethod
    def _load(cls, directory: Path, visited: set[Path]) -> Self:
        if directory in visited:
            raise ValueError(f'cassette overlay cycle detected at {directory.name!r}')
        visited.add(directory)

        manifest_value = _load_json(directory / 'manifest.json')
        manifest = CassetteManifest.from_json(manifest_value)
        overlay_path = directory / 'overlay.json'
        if overlay_path.exists():
            if manifest.origin != 'synthetic':
                raise ValueError('cassette with overlay.json must declare origin="synthetic"')
            cassette = cls._load_overlay(directory, manifest, overlay_path, visited)
        else:
            responses_value = _load_json(directory / 'responses.json')
            if not isinstance(responses_value, list):
                raise ValueError('cassette responses.json must contain a JSON array')
            cassette = cls(
                manifest=manifest,
                entries=[CassetteEntry.from_json(entry, directory) for entry in responses_value],
            )

        visited.remove(directory)
        return cassette

    @classmethod
    def _load_overlay(
        cls,
        directory: Path,
        manifest: CassetteManifest,
        overlay_path: Path,
        visited: set[Path],
    ) -> Self:
        overlay = _load_json(overlay_path)
        if not isinstance(overlay, dict):
            raise ValueError('cassette overlay.json must contain a JSON object')

        base_relative = _required_str(overlay, 'base_cassette')
        base_path = (directory / base_relative).resolve()
        if not base_path.is_relative_to(directory.parent.resolve()):
            raise ValueError('cassette overlay base_cassette must stay inside the network cassette directory')

        expected_hash = _required_str(overlay, 'base_manifest_sha256')
        base_manifest_path = base_path / 'manifest.json'
        try:
            actual_hash = hashlib.sha256(base_manifest_path.read_bytes()).hexdigest()
        except FileNotFoundError as error:
            raise ValueError(f'missing base cassette manifest: {base_path.name}') from error
        if actual_hash != expected_hash:
            raise ValueError(
                f'cassette overlay base manifest hash mismatch: expected {expected_hash!r}, got {actual_hash!r}'
            )

        base = cls._load(base_path, visited)
        if base.manifest.scenario_id != manifest.base_scenario_id:
            raise ValueError(
                'cassette overlay base scenario mismatch: '
                f'expected {manifest.base_scenario_id!r}, got {base.manifest.scenario_id!r}'
            )

        patches = overlay.get('patches')
        if not isinstance(patches, list) or not patches:
            raise ValueError('cassette overlay patches must be a non-empty JSON array')

        responses = copy.deepcopy(base._responses)
        for patch in patches:
            _apply_patch(responses, patch)

        cassette = cls(manifest=manifest, entries=[])
        cassette._responses = responses
        return cassette

    def replay(
        self,
        provider: ProviderName,
        method: str,
        params: dict[str, JsonValue] | None = None,
    ) -> JsonValue:
        normalized_params = params or {}
        key = self._key(provider, method, normalized_params)
        if key not in self._responses:
            raise KeyError(
                f'cassette has no response for provider={provider!r}, method={method!r}, params={normalized_params!r}'
            )
        return copy.deepcopy(self._responses[key])

    def assert_consensus_spec(self, expected: dict[str, JsonValue]) -> None:
        """Fail loudly when a cassette was recorded against a different fork specification."""
        mismatches = {
            key: (self.manifest.consensus_spec.get(key), expected_value)
            for key, expected_value in expected.items()
            if self.manifest.consensus_spec.get(key) != expected_value
        }
        if mismatches:
            raise ValueError(f'cassette consensus spec mismatch: {mismatches!r}')

    @staticmethod
    def _key(provider: ProviderName, method: str, params: dict[str, JsonValue]) -> str:
        return json.dumps([provider, method, params], sort_keys=True, separators=(',', ':'))


def _load_json(path: Path) -> JsonValue:
    try:
        if path.suffix == '.gz':
            with gzip.open(path, 'rt', encoding='utf-8') as source:
                return json.load(source)
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise ValueError(f'missing cassette file: {path.name}') from error
    except json.JSONDecodeError as error:
        raise ValueError(f'invalid JSON in cassette file: {path.name}') from error


def _required_str(value: dict[str, JsonValue], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f'cassette field {key!r} must be a non-empty string')
    return item


def _required_int(value: dict[str, JsonValue], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError(f'cassette field {key!r} must be an integer')
    return item


def _apply_patch(responses: dict[str, JsonValue], value: JsonValue) -> None:
    if not isinstance(value, dict):
        raise ValueError('cassette overlay patch must be a JSON object')

    provider = value.get('provider')
    if provider not in ('consensus', 'execution', 'keys_api'):
        raise ValueError(f'unsupported cassette overlay provider {provider!r}')
    method = _required_str(value, 'method')
    params = value.get('params', {})
    if not isinstance(params, dict):
        raise ValueError('cassette overlay patch params must be a JSON object')
    path = _required_str(value, 'path')
    if 'value' not in value:
        raise ValueError('cassette overlay patch must contain value')

    key = Cassette._key(provider, method, params)
    if key not in responses:
        raise ValueError(f'cassette overlay target does not exist: provider={provider!r}, method={method!r}')
    _replace_json_pointer(responses[key], path, value['value'])


def _replace_json_pointer(document: JsonValue, pointer: str, replacement: JsonValue) -> None:
    if not pointer.startswith('/'):
        raise ValueError(f'cassette overlay path must be a JSON pointer: {pointer!r}')
    tokens = [token.replace('~1', '/').replace('~0', '~') for token in pointer[1:].split('/')]
    if not tokens or tokens == ['']:
        raise ValueError('cassette overlay cannot replace the entire response')

    current = document
    for token in tokens[:-1]:
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ValueError(f'cassette overlay path does not exist: {pointer!r}')

    final = tokens[-1]
    if isinstance(current, dict) and final in current:
        current[final] = copy.deepcopy(replacement)
    elif isinstance(current, list) and final.isdecimal() and int(final) < len(current):
        current[int(final)] = copy.deepcopy(replacement)
    else:
        raise ValueError(f'cassette overlay path does not exist: {pointer!r}')
