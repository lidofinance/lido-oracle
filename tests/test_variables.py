import importlib
from pathlib import Path

import pytest

import src.variables as variables


DUMMY_MEMBER_PRIV_KEY = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'

SECRETS_FROM_FILE = [
    'LIDO_IPFS_TOKEN',
    'FILEBASE_IPFS_TOKEN',
    'OPSGENIE_API_KEY',
    'PERFORMANCE_DB_PASSWORD',
    'TELEMETRY_DATA_BUS_RPC',
]
URI_LISTS_FROM_FILE = ['EXECUTION_CLIENT_URI', 'CONSENSUS_CLIENT_URI', 'KEYS_API_URI']
ALL_FILE_VARIABLES = [
    *SECRETS_FROM_FILE,
    *URI_LISTS_FROM_FILE,
    'MEMBER_PRIV_KEY',
    'MEMBER_PRIV_KEY_2',
    'TELEMETRY_PRIV_KEY',
]


@pytest.mark.unit
class TestVariablesFromFile:
    @pytest.fixture()
    def reload_variables(self, monkeypatch: pytest.MonkeyPatch):
        for name in ALL_FILE_VARIABLES:
            monkeypatch.delenv(name, raising=False)
            monkeypatch.delenv(f'{name}_FILE', raising=False)

        def _reload():
            return importlib.reload(variables)

        yield _reload

        monkeypatch.undo()
        importlib.reload(variables)

    @staticmethod
    def _secret_file(tmp_path: Path, name: str, content: str) -> str:
        path = tmp_path / name
        path.write_text(content)
        return str(path)

    @pytest.mark.parametrize('name', SECRETS_FROM_FILE)
    def test_variables__secret_in_file__reads_value_from_file(self, name, monkeypatch, tmp_path, reload_variables):
        monkeypatch.setenv(f'{name}_FILE', self._secret_file(tmp_path, name, 'secret-value-from-file\n'))

        reloaded = reload_variables()

        assert getattr(reloaded, name) == 'secret-value-from-file'

    @pytest.mark.parametrize('name', URI_LISTS_FROM_FILE)
    def test_variables__uri_list_in_file__splits_value_from_file(self, name, monkeypatch, tmp_path, reload_variables):
        monkeypatch.setenv(f'{name}_FILE', self._secret_file(tmp_path, name, 'http://first:1,http://second:2\n'))

        reloaded = reload_variables()

        assert getattr(reloaded, name) == ['http://first:1', 'http://second:2']

    @pytest.mark.parametrize('name', URI_LISTS_FROM_FILE)
    def test_variables__uri_list_in_env__splits_value_from_env(self, name, monkeypatch, reload_variables):
        monkeypatch.setenv(name, 'http://first:1,http://second:2')

        reloaded = reload_variables()

        assert getattr(reloaded, name) == ['http://first:1', 'http://second:2']

    def test_check_uri_required_variables__empty_uri_file__raises(self, monkeypatch, tmp_path, reload_variables):
        for name in URI_LISTS_FROM_FILE:
            monkeypatch.setenv(name, 'http://localhost')
        monkeypatch.setenv('EXECUTION_CLIENT_URI_FILE', self._secret_file(tmp_path, 'EXECUTION_CLIENT_URI', ''))

        reloaded = reload_variables()

        assert reloaded.check_uri_required_variables() == ['EXECUTION_CLIENT_URI']

    def test_variables__empty_member_key_file__dry_mode(self, monkeypatch, tmp_path, reload_variables):
        monkeypatch.setenv('MEMBER_PRIV_KEY_FILE', self._secret_file(tmp_path, 'MEMBER_PRIV_KEY', '\n'))

        reloaded = reload_variables()

        assert reloaded.ACCOUNT is None
        assert reloaded.PUBLIC_ENV_VARS['ACCOUNT'] == 'Dry'

    def test_variables__member_key_file__account_is_set(self, monkeypatch, tmp_path, reload_variables):
        monkeypatch.setenv(
            'MEMBER_PRIV_KEY_FILE', self._secret_file(tmp_path, 'MEMBER_PRIV_KEY', DUMMY_MEMBER_PRIV_KEY + '\n')
        )

        reloaded = reload_variables()

        assert reloaded.ACCOUNT is not None

    def test_variables__empty_db_password_file__default_password(self, monkeypatch, tmp_path, reload_variables):
        monkeypatch.setenv('PERFORMANCE_DB_PASSWORD_FILE', self._secret_file(tmp_path, 'PERFORMANCE_DB_PASSWORD', ''))

        reloaded = reload_variables()

        assert reloaded.PERFORMANCE_DB_PASSWORD == 'performance'

    def test_variables__nothing_set__defaults_as_before(self, reload_variables):
        reloaded = reload_variables()

        assert reloaded.EXECUTION_CLIENT_URI == ['']
        assert reloaded.TELEMETRY_DATA_BUS_RPC == ''
        assert reloaded.OPSGENIE_API_KEY == ''
        assert reloaded.LIDO_IPFS_TOKEN is None
        assert reloaded.FILEBASE_IPFS_TOKEN is None
        assert reloaded.PERFORMANCE_DB_PASSWORD == 'performance'


@pytest.mark.unit
class TestLogSecrets:
    @pytest.fixture()
    def reload_variables(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv('PERFORMANCE_DB_PASSWORD', raising=False)
        monkeypatch.delenv('PERFORMANCE_DB_PASSWORD_FILE', raising=False)

        def _reload():
            return importlib.reload(variables)

        yield _reload

        monkeypatch.undo()
        importlib.reload(variables)

    def test_log_secrets__default_db_password__not_masked(self, reload_variables):
        reloaded = reload_variables()

        assert reloaded.LOG_SECRETS['PERFORMANCE_DB_PASSWORD'] is None

    def test_log_secrets__custom_db_password__masked(self, monkeypatch, reload_variables):
        monkeypatch.setenv('PERFORMANCE_DB_PASSWORD', 'custom-db-password')

        reloaded = reload_variables()

        assert reloaded.LOG_SECRETS['PERFORMANCE_DB_PASSWORD'] == 'custom-db-password'

    def test_log_secrets__all_private_variables__present(self):
        assert set(variables.LOG_SECRETS) == set(variables.PRIVATE_ENV_VARS)
