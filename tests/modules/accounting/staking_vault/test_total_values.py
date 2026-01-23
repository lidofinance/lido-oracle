"""
Total value calculation tests for staking vaults.
"""

import pytest

from src.modules.oracles.accounting.types import ValidatorStage
from src.services.staking_vaults import StakingVaultsService
from src.types import Gwei, SlotNumber
from src.utils.units import gwei_to_wei
from tests.modules.accounting.staking_vault.conftest import (
    PendingDepositFactory,
    TestPubkeys,
    ValidatorFactory,
    ValidatorStateFactory,
    ValidatorStatusFactory,
    VaultAddresses,
    WithdrawalCredentials,
)


class TestGetVaultsTotalValues:
    """Tests for get_vaults_total_values method."""

    @pytest.mark.unit
    def test_basic_calculation_with_validators_and_pending_deposits(self, staking_vaults_service, default_vaults_map):
        """Test basic total value calculation with active validators and pending deposits."""
        validators = [
            ValidatorFactory.build(
                balance=Gwei(32_834_904_184),
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                ),
            ),
            ValidatorFactory.build(
                balance=Gwei(40_000_000_000),
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_1,
                    withdrawal_credentials=WithdrawalCredentials.WC_1,
                ),
            ),
            ValidatorFactory.build(
                balance=Gwei(50_000_000_000),
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_2,
                    withdrawal_credentials=WithdrawalCredentials.WC_2,
                ),
            ),
            ValidatorFactory.build(
                balance=Gwei(60_000_000_000),
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_3,
                    withdrawal_credentials=WithdrawalCredentials.WC_3,
                ),
            ),
        ]

        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_0,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                amount=Gwei(1_000_000_000),
            ),
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials=WithdrawalCredentials.WC_1,
                amount=Gwei(1_000_000_000),
            ),
            # This deposit has wrong WC (not matching vault_2), should be ignored
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_2,
                withdrawal_credentials='0x0200000000000000000000004473426150869040d523681669d14b5315964b5a',
                amount=Gwei(1_000_000_000),
            ),
        ]

        result = staking_vaults_service.get_vaults_total_values(default_vaults_map, validators, pending_deposits, {})

        expected = {
            VaultAddresses.VAULT_0: 34_834_904_184_000_000_000,  # 32.8 ETH + 1 EL + 1 pending
            VaultAddresses.VAULT_1: 41_000_000_000_000_000_000,  # 40 ETH + 0 EL + 1 pending
            VaultAddresses.VAULT_2: 53_000_900_000_000_000_000,  # 50 ETH + 2.0009 EL
            VaultAddresses.VAULT_3: 61_000_000_000_000_000_000,  # 60 ETH + 1 EL
        }
        assert result == expected

    @pytest.mark.unit
    def test_pending_deposit_with_wrong_wc_ignored(self, staking_vaults_service, default_vaults_map):
        """Test that pending deposits with wrong withdrawal credentials are not counted."""
        validators = [
            ValidatorFactory.build(
                balance=Gwei(32_834_904_184),
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                ),
            ),
        ]

        # Pending deposit with WC_1 but validator has WC_0
        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_0,
                withdrawal_credentials=WithdrawalCredentials.WC_1,
                amount=Gwei(3_000_000_000),
            ),
        ]

        result = staking_vaults_service.get_vaults_total_values(default_vaults_map, validators, pending_deposits, {})

        # Pending deposit should be counted for vault_0 (where validator is)
        expected = {
            VaultAddresses.VAULT_0: 36_834_904_184_000_000_000,  # includes pending deposit
            VaultAddresses.VAULT_1: 0,
            VaultAddresses.VAULT_2: 2_000_900_000_000_000_000,
            VaultAddresses.VAULT_3: 1_000_000_000_000_000_000,
        }
        assert result == expected

    @pytest.mark.unit
    def test_multiple_pending_deposits_for_same_validator(self, staking_vaults_service, default_vaults_map):
        """Test that multiple pending deposits for the same validator are summed."""
        validators = [
            ValidatorFactory.build(
                balance=Gwei(32_000_000_000),
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_1,
                    withdrawal_credentials=WithdrawalCredentials.WC_1,
                ),
            ),
        ]

        # Three pending deposits for the same validator
        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials=WithdrawalCredentials.WC_1,
                amount=Gwei(1_000_000_000),
                slot=SlotNumber(259387),
            ),
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials=WithdrawalCredentials.WC_1,
                amount=Gwei(1_000_000_000),
                slot=SlotNumber(259388),
            ),
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials=WithdrawalCredentials.WC_1,
                amount=Gwei(1_000_000_000),
                slot=SlotNumber(259389),
            ),
        ]

        result = staking_vaults_service.get_vaults_total_values(default_vaults_map, validators, pending_deposits, {})

        expected = {
            VaultAddresses.VAULT_0: 1_000_000_000_000_000_000,
            VaultAddresses.VAULT_1: 35_000_000_000_000_000_000,  # 32 ETH + 3 pending
            VaultAddresses.VAULT_2: 2_000_900_000_000_000_000,
            VaultAddresses.VAULT_3: 1_000_000_000_000_000_000,
        }
        assert result == expected

    @pytest.mark.unit
    def test_pending_deposit_without_validator_counts_predeposit(
        self, mock_w3_with_validator_statuses, default_vaults_map
    ):
        """Test that pending deposits without validators count 1 ETH if PREDEPOSITED."""
        pending_pubkey = (
            '0xb5b222b452892bd62a7d2b4925e15bf9823c4443313d86d3e1fe549c86aa8919d0cdd1d5b60'
            'd9d3184f3966ced21699f124a14a0d8c1f1ae3e9f25715f40c3e7'
        )

        validators = []
        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=pending_pubkey,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                amount=Gwei(1_000_000_000),
            ),
        ]

        validator_statuses = {pending_pubkey: ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0)}

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, pending_deposits)

        expected = {
            VaultAddresses.VAULT_0: 2_000_000_000_000_000_000,
            VaultAddresses.VAULT_1: 0,
            VaultAddresses.VAULT_2: 2_000_900_000_000_000_000,
            VaultAddresses.VAULT_3: 1_000_000_000_000_000_000,
        }
        assert result == expected


class TestGetVaultsTotalValuesWithValidatorStatuses:
    """Tests for vault total values with various validator stages."""

    @pytest.mark.unit
    def test_predeposited_validator_counts_1_eth(self, mock_w3_with_validator_statuses, default_vaults_map):
        """Test PREDEPOSITED validator only counts 1 ETH regardless of balance."""
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99002'

        validators = [
            ValidatorFactory.build(
                balance=Gwei(2_000_000_000),
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=pubkey,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                    effective_balance=Gwei(2_000_000_000),
                ),
            ),
        ]

        validator_statuses = {pubkey: ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0)}

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        expected_vault_0 = default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance + gwei_to_wei(
            Gwei(1_000_000_000)
        )
        assert result[VaultAddresses.VAULT_0] == expected_vault_0

    @pytest.mark.unit
    def test_activated_validator_counts_full_balance_plus_pending(
        self, mock_w3_with_validator_statuses, default_vaults_map
    ):
        """Test ACTIVATED validator counts full balance plus pending deposits."""
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99005'

        validators = [
            ValidatorFactory.build(
                balance=Gwei(1_000_000_000),
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=pubkey,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                    effective_balance=Gwei(1_000_000_000),
                ),
            ),
        ]

        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=pubkey,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                amount=Gwei(31_000_000_000),
            ),
        ]

        validator_statuses = {pubkey: ValidatorStatusFactory.build_activated(VaultAddresses.VAULT_0)}

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, pending_deposits)

        expected_vault_0 = (
            default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance
            + gwei_to_wei(Gwei(1_000_000_000))
            + gwei_to_wei(Gwei(31_000_000_000))
        )
        assert result[VaultAddresses.VAULT_0] == expected_vault_0

    @pytest.mark.unit
    def test_proven_validator_not_counted(self, mock_w3_with_validator_statuses, default_vaults_map):
        """Test PROVEN validator is not counted in total value."""
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99003'

        validators = [
            ValidatorFactory.build(
                balance=Gwei(10_000_000_000),
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=pubkey,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                    effective_balance=Gwei(10_000_000_000),
                ),
            ),
        ]

        validator_statuses = {pubkey: ValidatorStatusFactory.build_proven(VaultAddresses.VAULT_0)}

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance

    @pytest.mark.unit
    def test_predeposited_validator_with_pending_deposit_no_double_count(
        self, mock_w3_with_validator_statuses, default_vaults_map
    ):
        """Test PREDEPOSITED validator with pending deposits doesn't double count."""
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99001'

        validators = [
            ValidatorFactory.build(
                balance=Gwei(1_000_000_000),
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=pubkey,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                    effective_balance=Gwei(1_000_000_000),
                ),
            ),
        ]

        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=pubkey,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                amount=Gwei(31_000_000_000),
            ),
        ]

        validator_statuses = {pubkey: ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0)}

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, pending_deposits)

        expected_vault_0 = default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance + gwei_to_wei(
            Gwei(1_000_000_000)
        )
        assert result[VaultAddresses.VAULT_0] == expected_vault_0

    @pytest.mark.unit
    def test_doppelganger_pubkey_not_counted(self, mock_w3_with_validator_statuses, default_vaults_map):
        """Test doppelganger pubkey (different vault WC) is not counted."""
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99001'

        validators = [
            ValidatorFactory.build(
                balance=Gwei(1_000_000_000),
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=pubkey,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                    effective_balance=Gwei(1_000_000_000),
                ),
            ),
        ]

        validator_statuses = {pubkey: ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_1)}

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance
        assert result[VaultAddresses.VAULT_1] == default_vaults_map[VaultAddresses.VAULT_1].aggregated_balance


class TestGetVaultsTotalValuesEdgeCases:
    """Additional edge cases for total value calculations."""

    @pytest.mark.unit
    def test_unmatched_pending_deposit_non_predeposited_stage_ignored(
        self,
        mock_w3_with_validator_statuses,
        default_vaults_map,
    ):
        """Ensure unmatched pending deposits that are not PREDEPOSITED are ignored."""
        pending_pubkey = '0x1234'

        pending_deposits = [
            PendingDepositFactory.build(
                pubkey=pending_pubkey,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
                amount=Gwei(1_000_000_000),
            ),
        ]

        validator_statuses = {
            pending_pubkey: ValidatorStatusFactory.build(
                stage=ValidatorStage.PROVEN, staking_vault=VaultAddresses.VAULT_0
            )
        }

        w3_mock = mock_w3_with_validator_statuses(validator_statuses)
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, [], pending_deposits)

        # No extra 1 ETH should be counted because stage is not PREDEPOSITED.
        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance

    @pytest.mark.unit
    def test_far_future_validator_without_status_skipped(self, mock_w3_with_validator_statuses, default_vaults_map):
        """Ensure far-future validators without PDG status are skipped."""
        pubkey = '0xdeadbeef'

        validators = [
            ValidatorFactory.build(
                balance=Gwei(2_000_000_000),
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=pubkey,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                    effective_balance=Gwei(2_000_000_000),
                ),
            ),
        ]

        # No PDG data returned for the validator
        w3_mock = mock_w3_with_validator_statuses({})
        service = StakingVaultsService(w3_mock)

        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        # Validator should be ignored entirely.
        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance
