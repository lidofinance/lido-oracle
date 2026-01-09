import pytest

from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import (
    TestPubkeys,
    ValidatorFactory,
    ValidatorStateFactory,
    VaultAddresses,
    WithdrawalCredentials,
)


class TestGetValidatorsByVault:
    """Tests for _get_validators_by_vault static method."""

    @pytest.mark.unit
    def test_single_validator(self, default_vaults_map):
        """Verifies that a single validator is correctly grouped into its vault based
        on withdrawal credentials. Ensures basic validator-to-vault mapping works correctly.
        """
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                ),
            ),
        ]

        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        assert len(result) == 1
        assert VaultAddresses.VAULT_0 in result
        assert len(result[VaultAddresses.VAULT_0]) == 1

    @pytest.mark.unit
    def test_multiple_validators_different_vaults(self, default_vaults_map):
        """Verifies that multiple validators are correctly grouped into their respective
        vaults based on withdrawal credentials. Ensures validators are mapped to the
        correct vaults when multiple vaults exist.
        """
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

        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        assert len(result) == 3
        assert VaultAddresses.VAULT_0 in result
        assert VaultAddresses.VAULT_1 in result
        assert VaultAddresses.VAULT_2 in result
        assert len(result[VaultAddresses.VAULT_0]) == 1
        assert len(result[VaultAddresses.VAULT_1]) == 1
        assert len(result[VaultAddresses.VAULT_2]) == 1

    @pytest.mark.unit
    def test_multiple_validators_same_vault(self, default_vaults_map):
        """Verifies that multiple validators with the same withdrawal credentials are
        correctly grouped into the same vault. Ensures vaults can contain multiple
        validators correctly.
        """
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(withdrawal_credentials=WithdrawalCredentials.WC_0),
            )
            for _ in range(3)
        ]

        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        assert len(result) == 1
        assert VaultAddresses.VAULT_0 in result
        assert len(result[VaultAddresses.VAULT_0]) == 3

    @pytest.mark.unit
    def test_unknown_withdrawal_credentials_excluded(self, default_vaults_map):
        """Verifies that validators with withdrawal credentials not matching any vault
        are excluded from the result. Ensures only validators belonging to tracked vaults
        are included in the mapping.
        """
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

        result = StakingVaultsService._get_validators_by_vault(validators, default_vaults_map)

        assert len(result) == 1
        assert VaultAddresses.VAULT_0 in result
        assert all(validators[1] not in vault_validators for vault_validators in result.values())

    @pytest.mark.unit
    def test_empty_validators(self, default_vaults_map):
        """Verifies that an empty validators list returns an empty result dictionary.
        Ensures the function handles edge cases gracefully without errors.
        """
        result = StakingVaultsService._get_validators_by_vault([], default_vaults_map)
        assert result == {}

    @pytest.mark.unit
    def test_empty_vaults_map(self):
        """Verifies that when no vaults are tracked, validators are not grouped into
        any vault and an empty result is returned. Ensures validators are only mapped
        to existing vaults.
        """
        validators = [
            ValidatorFactory.build_active(
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                validator=ValidatorStateFactory.build(withdrawal_credentials=WithdrawalCredentials.WC_0),
            ),
        ]

        result = StakingVaultsService._get_validators_by_vault(validators, {})
        assert result == {}
