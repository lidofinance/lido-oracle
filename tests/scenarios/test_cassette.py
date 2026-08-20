"""Offline tests for the scenario cassette format and replay lookup."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from tests.scenarios.cassette import Cassette


def _write_cassette(directory: Path, *, schema_version: int = 1) -> None:
    manifest = {
        'schema_version': schema_version,
        'scenario_id': 'AC-02-fallback-withheld-payload',
        'network': 'epbs-devnet',
        'module': 'accounting',
        'ref_slot': 319,
        'recorded_at': '2026-07-22T12:00:00Z',
        'consensus_spec': {'GLOAS_FORK_EPOCH': '5', 'SLOTS_PER_EPOCH': '32'},
    }
    responses = [
        {
            'provider': 'consensus',
            'method': 'get_state_view',
            'params': {'state_id': '0xabc'},
            'response': {
                'slot': '319',
                'payload_expected_withdrawals': [{'validator_index': '7', 'amount': '100'}],
            },
        },
        {
            'provider': 'execution',
            'method': 'get_balance',
            'params': {'address': '0x123', 'block': '0xdef'},
            'response': '42',
        },
    ]
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (directory / 'responses.json').write_text(json.dumps(responses), encoding='utf-8')


@pytest.mark.unit
@pytest.mark.scenario
class TestCassetteReplay:
    def test_load__valid_cassette__replays_exact_response(self, tmp_path: Path) -> None:
        # Arrange
        _write_cassette(tmp_path)
        cassette = Cassette.load(tmp_path)

        # Act
        response = cassette.replay('consensus', 'get_state_view', {'state_id': '0xabc'})

        # Assert
        assert cassette.manifest.scenario_id == 'AC-02-fallback-withheld-payload'
        assert cassette.manifest.ref_slot == 319
        assert response == {
            'slot': '319',
            'payload_expected_withdrawals': [{'validator_index': '7', 'amount': '100'}],
        }

    def test_replay__caller_mutates_response__keeps_recording_immutable(self, tmp_path: Path) -> None:
        # Arrange
        _write_cassette(tmp_path)
        cassette = Cassette.load(tmp_path)
        response = cassette.replay('consensus', 'get_state_view', {'state_id': '0xabc'})
        assert isinstance(response, dict)

        # Act
        response['slot'] = 'changed'

        # Assert
        replayed = cassette.replay('consensus', 'get_state_view', {'state_id': '0xabc'})
        assert isinstance(replayed, dict)
        assert replayed['slot'] == '319'

    def test_replay__unknown_call__raises_descriptive_key_error(self, tmp_path: Path) -> None:
        # Arrange
        _write_cassette(tmp_path)
        cassette = Cassette.load(tmp_path)

        # Act / Assert
        with pytest.raises(KeyError, match="method='get_block'"):
            cassette.replay('consensus', 'get_block', {'slot': '319'})

    def test_load__unsupported_schema_version__rejects_cassette(self, tmp_path: Path) -> None:
        # Arrange
        _write_cassette(tmp_path, schema_version=2)

        # Act / Assert
        with pytest.raises(ValueError, match='unsupported cassette schema version'):
            Cassette.load(tmp_path)

    def test_assert_consensus_spec__fork_epoch_changed__rejects_stale_cassette(self, tmp_path: Path) -> None:
        # Arrange
        _write_cassette(tmp_path)
        cassette = Cassette.load(tmp_path)

        # Act / Assert
        with pytest.raises(ValueError, match='GLOAS_FORK_EPOCH'):
            cassette.assert_consensus_spec({'GLOAS_FORK_EPOCH': '6', 'SLOTS_PER_EPOCH': '32'})

    def test_load__response_stored_in_gzip_file__replays_response(self, tmp_path: Path) -> None:
        # Arrange
        _write_cassette(tmp_path)
        compressed_response = {'slot': '319', 'validators': [{'effective_balance': '32000000000'}]}
        with gzip.open(tmp_path / 'state.json.gz', 'wt', encoding='utf-8') as output:
            json.dump(compressed_response, output)
        responses = [
            {
                'provider': 'consensus',
                'method': 'get_state_view',
                'params': {'state_id': '0xcompressed'},
                'response_file': 'state.json.gz',
            }
        ]
        (tmp_path / 'responses.json').write_text(json.dumps(responses), encoding='utf-8')

        # Act
        cassette = Cassette.load(tmp_path)
        response = cassette.replay('consensus', 'get_state_view', {'state_id': '0xcompressed'})

        # Assert
        assert response == compressed_response

    def test_load__synthetic_overlay__patches_base_without_mutating_recording(self, tmp_path: Path) -> None:
        # Arrange
        base_path = tmp_path / 'base'
        base_path.mkdir()
        _write_cassette(base_path)
        synthetic_path = tmp_path / 'synthetic'
        synthetic_path.mkdir()
        base_manifest_hash = hashlib.sha256((base_path / 'manifest.json').read_bytes()).hexdigest()
        manifest = {
            'schema_version': 1,
            'scenario_id': 'AC-02-synthetic-withheld-payload',
            'network': 'epbs-devnet',
            'module': 'accounting',
            'ref_slot': 319,
            'recorded_at': '2026-07-22T12:00:00Z',
            'consensus_spec': {'GLOAS_FORK_EPOCH': '5', 'SLOTS_PER_EPOCH': '32'},
            'origin': 'synthetic',
            'base_scenario_id': 'AC-02-fallback-withheld-payload',
        }
        overlay = {
            'base_cassette': '../base',
            'base_manifest_sha256': base_manifest_hash,
            'patches': [
                {
                    'provider': 'consensus',
                    'method': 'get_state_view',
                    'params': {'state_id': '0xabc'},
                    'path': '/payload_expected_withdrawals',
                    'value': [{'validator_index': '384', 'amount': '1000000000'}],
                }
            ],
        }
        (synthetic_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (synthetic_path / 'overlay.json').write_text(json.dumps(overlay), encoding='utf-8')

        # Act
        cassette = Cassette.load(synthetic_path)
        synthetic = cassette.replay('consensus', 'get_state_view', {'state_id': '0xabc'})
        recorded = Cassette.load(base_path).replay('consensus', 'get_state_view', {'state_id': '0xabc'})

        # Assert
        assert cassette.manifest.origin == 'synthetic'
        assert cassette.manifest.base_scenario_id == 'AC-02-fallback-withheld-payload'
        assert isinstance(synthetic, dict)
        assert synthetic['payload_expected_withdrawals'] == [{'validator_index': '384', 'amount': '1000000000'}]
        assert isinstance(recorded, dict)
        assert recorded['payload_expected_withdrawals'] == [{'validator_index': '7', 'amount': '100'}]

    def test_load__synthetic_overlay_base_changed__rejects_stale_patch(self, tmp_path: Path) -> None:
        # Arrange
        base_path = tmp_path / 'base'
        base_path.mkdir()
        _write_cassette(base_path)
        synthetic_path = tmp_path / 'synthetic'
        synthetic_path.mkdir()
        manifest = {
            'schema_version': 1,
            'scenario_id': 'AC-02-synthetic-withheld-payload',
            'network': 'epbs-devnet',
            'module': 'accounting',
            'ref_slot': 319,
            'recorded_at': '2026-07-22T12:00:00Z',
            'consensus_spec': {'GLOAS_FORK_EPOCH': '5'},
            'origin': 'synthetic',
            'base_scenario_id': 'AC-02-fallback-withheld-payload',
        }
        overlay = {
            'base_cassette': '../base',
            'base_manifest_sha256': '0' * 64,
            'patches': [
                {
                    'provider': 'consensus',
                    'method': 'get_state_view',
                    'params': {'state_id': '0xabc'},
                    'path': '/slot',
                    'value': '318',
                }
            ],
        }
        (synthetic_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (synthetic_path / 'overlay.json').write_text(json.dumps(overlay), encoding='utf-8')

        # Act / Assert
        with pytest.raises(ValueError, match='base manifest hash mismatch'):
            Cassette.load(synthetic_path)
