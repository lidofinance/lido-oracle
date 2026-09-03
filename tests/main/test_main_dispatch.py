from unittest.mock import patch

import pytest

from src import variables
from src.main import main
from src.types import OracleModuleName
from tests.conftest import DUMMY_ADDRESS


@pytest.mark.unit
class TestMainDispatch:
    @pytest.fixture
    def uris(self, monkeypatch):
        monkeypatch.setattr(variables, 'EXECUTION_CLIENT_URI', ['http://el'])
        monkeypatch.setattr(variables, 'CONSENSUS_CLIENT_URI', ['http://cl'])
        monkeypatch.setattr(variables, 'KEYS_API_URI', ['http://kapi'])

    def test_main__csm_0x02__runs_csm_0x02_entrypoint(self, monkeypatch, uris):
        # Arrange
        monkeypatch.setattr(variables, 'STAKING_MODULE_ADDRESS', DUMMY_ADDRESS)
        target = 'src.modules.oracles.staking_modules.community_staking_0x02.entrypoint.run'

        # Act
        with patch(target) as run:
            main(OracleModuleName.CSM_0X02)

        # Assert
        run.assert_called_once_with()

    def test_main__csm_0x02_without_module_address__raises(self, monkeypatch, uris):
        # Arrange
        monkeypatch.setattr(variables, 'STAKING_MODULE_ADDRESS', None)

        # Act / Assert
        with pytest.raises(ValueError, match='STAKING_MODULE_ADDRESS'):
            main(OracleModuleName.CSM_0X02)

    def test_main__csm_0x02__does_not_require_locator(self, monkeypatch, uris):
        # Arrange
        monkeypatch.setattr(variables, 'STAKING_MODULE_ADDRESS', DUMMY_ADDRESS)
        monkeypatch.setattr(variables, 'LIDO_LOCATOR_ADDRESS', None)

        # Act
        errors = variables.check_all_required_variables(OracleModuleName.CSM_0X02)

        # Assert
        assert errors == []
