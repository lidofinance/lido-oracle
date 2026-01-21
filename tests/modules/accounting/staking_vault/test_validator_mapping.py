import pytest

from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import (
    TestPubkeys,
    ValidatorFactory,
    ValidatorStateFactory,
    VaultAddresses,
    WithdrawalCredentials,
)

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestGetValidatorsByVault:

    def test_single_validator(self, default_vaults_map):
        # Setup
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                ),
            ),
        ]

        # Act
        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        # Assert
        assert len(result) == 1
        assert VaultAddresses.VAULT_0 in result
        assert len(result[VaultAddresses.VAULT_0]) == 1

    def test_multiple_validators_different_vaults(self, default_vaults_map):
        # Setup
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                ),
            ),
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_1,
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_1,
                    withdrawal_credentials=WithdrawalCredentials.WC_1,
                ),
            ),
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_2,
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_2,
                    withdrawal_credentials=WithdrawalCredentials.WC_2,
                ),
            ),
        ]

        # Act
        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        # Assert
        assert len(result) == 3
        assert VaultAddresses.VAULT_0 in result
        assert VaultAddresses.VAULT_1 in result
        assert VaultAddresses.VAULT_2 in result
        assert len(result[VaultAddresses.VAULT_0]) == 1
        assert len(result[VaultAddresses.VAULT_1]) == 1
        assert len(result[VaultAddresses.VAULT_2]) == 1

    def test_multiple_validators_same_vault(self, default_vaults_map):
        # Setup
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(withdrawal_credentials=WithdrawalCredentials.WC_0),
            )
            for _ in range(3)
        ]

        # Act
        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        # Assert
        assert len(result) == 1
        assert VaultAddresses.VAULT_0 in result
        assert len(result[VaultAddresses.VAULT_0]) == 3

    def test_unknown_withdrawal_credentials_excluded(self, default_vaults_map):
        # Setup
        unknown_wc = '0x0200000000000000000000000000000000000000000000000000000000000000'
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(withdrawal_credentials=WithdrawalCredentials.WC_0),
            ),
            ValidatorFactory.build_active(
                withdrawal_credentials=unknown_wc,
                validator=ValidatorStateFactory.build(withdrawal_credentials=unknown_wc),
            ),
        ]

        # Act
        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        # Assert
        assert len(result) == 1
        assert VaultAddresses.VAULT_0 in result
        assert all(validators[1] not in vault_validators for vault_validators in result.values())

    def test_empty_validators(self, default_vaults_map):
        result = StakingVaultsService._get_validators_by_vault([], default_vaults_map)
        assert result == {}

    def test_empty_vaults_map(self):
        # Setup
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(withdrawal_credentials=WithdrawalCredentials.WC_0),
            ),
        ]

        # Act
        result = StakingVaultsService._get_validators_by_vault(validators, {})

        # Assert
        assert result == {}
