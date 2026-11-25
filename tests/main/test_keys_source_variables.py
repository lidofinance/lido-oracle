from unittest.mock import Mock, patch

import pytest

from src import variables
from src.modules.oracles.common.runtime import check_providers_chain_ids
from src.types import KeysSource
from src.utils.exception import IncompatibleException


@pytest.mark.unit
class TestKeysSourceVariables:
    @patch.object(variables, 'KEYS_API_URI', [''])
    @patch.object(variables, 'EXECUTION_CLIENT_URI', ['http://el'])
    @patch.object(variables, 'CONSENSUS_CLIENT_URI', ['http://cl'])
    def test_check_uri_required_variables__keys_api_source_without_uri__requires_keys_api_uri(self):
        with patch.object(variables, 'KEYS_SOURCE', KeysSource.KEYS_API):
            assert variables.check_uri_required_variables() == ['KEYS_API_URI']

    @patch.object(variables, 'KEYS_API_URI', [''])
    @patch.object(variables, 'EXECUTION_CLIENT_URI', ['http://el'])
    @patch.object(variables, 'CONSENSUS_CLIENT_URI', ['http://cl'])
    def test_check_uri_required_variables__onchain_source_without_uri__does_not_require_keys_api_uri(self):
        with patch.object(variables, 'KEYS_SOURCE', KeysSource.ONCHAIN):
            assert variables.check_uri_required_variables() == []


@pytest.mark.unit
class TestCheckProvidersChainIds:
    @staticmethod
    def make_web3(el_chain_id: int) -> tuple[Mock, Mock]:
        web3 = Mock()
        web3.provider.check_providers_consistency.return_value = el_chain_id
        cc = Mock()
        cc.check_providers_consistency.return_value = 1
        return web3, cc

    def test_check_providers_chain_ids__onchain_keys_same_chain__passes(self):
        web3, cc = self.make_web3(el_chain_id=1)

        check_providers_chain_ids(web3, cc, None)

    def test_check_providers_chain_ids__onchain_keys_different_chain__raises(self):
        web3, cc = self.make_web3(el_chain_id=560048)

        with pytest.raises(IncompatibleException):
            check_providers_chain_ids(web3, cc, None)

    def test_check_providers_chain_ids__keys_api_different_chain__raises(self):
        web3, cc = self.make_web3(el_chain_id=1)
        kac = Mock()
        kac.check_providers_consistency.return_value = 560048

        with pytest.raises(IncompatibleException):
            check_providers_chain_ids(web3, cc, kac)
