# pylint: disable=protected-access
import unittest
import pytest
from typing import Any
from unittest.mock import Mock

from src.providers.consistency import ProviderConsistencyModule, NotHealthyProvider, InconsistentProviders


@pytest.mark.unit
class TestProviderConsistencyModule(unittest.TestCase):
    def setUp(self):
        # Set up a concrete subclass for testing
        class TestProviderConsistencyModule(ProviderConsistencyModule):
            def get_all_providers(self) -> list[Any]:
                return ["provider1", "provider2", "provider3"]

            def _get_chain_id_with_provider(self, provider_index: int) -> int:
                return 1  # Mocked chain id for all providers

        self.provider_module = TestProviderConsistencyModule()

    def test_check_providers_consistency_success(self):
        """Test all providers return the same chain_id."""
        self.provider_module._get_chain_id_with_provider = Mock()
        self.provider_module._get_chain_id_with_provider.side_effect = [1, 1, 1]

        result = self.provider_module.check_providers_consistency()
        self.assertEqual(result, 1, "Expected consistent chain_id for all providers")

    def test_check_providers_consistency_inconsistent(self):
        """Test that inconsistent providers raise an InconsistentProviders exception."""
        self.provider_module._get_chain_id_with_provider = Mock()
        self.provider_module._get_chain_id_with_provider.side_effect = [1, 2, 1]

        with self.assertRaises(InconsistentProviders) as context:
            self.provider_module.check_providers_consistency()

        self.assertIn("Different chain ids detected", str(context.exception))

    def test_check_providers_consistency_not_healthy(self):
        """Test that a NotHealthyProvider exception is raised if a provider is not responding."""
        self.provider_module._get_chain_id_with_provider = Mock()
        self.provider_module._get_chain_id_with_provider.side_effect = [1, Exception("Provider not responding"), 1]

        with self.assertRaises(NotHealthyProvider) as context:
            self.provider_module.check_providers_consistency()

        self.assertIn("Provider [1] does not responding", str(context.exception))

    def test_check_providers_consistency_no_providers(self):
        """Test that if no providers are available, None is returned."""

        class NoProvidersModule(ProviderConsistencyModule):
            def get_all_providers(self) -> list[Any]:
                return []  # No providers

            def _get_chain_id_with_provider(self, provider_index: int) -> int:
                return 1

        no_providers_module = NoProvidersModule()
        result = no_providers_module.check_providers_consistency()
        self.assertIsNone(result, "Expected None when no providers are available")


if __name__ == '__main__':
    unittest.main()
