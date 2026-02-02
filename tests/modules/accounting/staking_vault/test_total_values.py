from unittest.mock import ANY, MagicMock, call

import pytest

from src.constants import MIN_DEPOSIT_AMOUNT
from src.modules.accounting.types import ValidatorStage
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

# =============================================================================
# Helper Functions
# =============================================================================


def configure_validator_statuses(web3, validator_statuses):
    lazy_oracle = MagicMock()

    def get_validator_statuses(pubkeys, *args, **kwargs):
        return {k: v for k, v in validator_statuses.items() if k in pubkeys}

    lazy_oracle.get_validator_statuses.side_effect = get_validator_statuses
    web3.lido_contracts.lazy_oracle = lazy_oracle


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestGetVaultsTotalValues:

    def test_basic_calculation_with_validators_and_pending_deposits(self, web3, default_vaults_map):
        # Setup
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

        configure_validator_statuses(web3, {})
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(
            vaults=default_vaults_map,
            validators=validators,
            pending_deposits=pending_deposits,
            block_identifier="latest",
        )

        # Assert
        expected = {
            VaultAddresses.VAULT_0: 34_834_904_184_000_000_000,  # 32.8 ETH + 1 EL + 1 pending
            VaultAddresses.VAULT_1: 41_000_000_000_000_000_000,  # 40 ETH + 0 EL + 1 pending
            VaultAddresses.VAULT_2: 53_000_900_000_000_000_000,  # 50 ETH + 2.0009 EL
            VaultAddresses.VAULT_3: 61_000_000_000_000_000_000,  # 60 ETH + 1 EL
        }
        assert result == expected

    def test_pending_deposit_with_wrong_wc_ignored(self, web3, default_vaults_map):
        # Setup
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

        configure_validator_statuses(web3, {})
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(
            vaults=default_vaults_map,
            validators=validators,
            pending_deposits=pending_deposits,
            block_identifier="latest",
        )

        # Assert
        # Pending deposit should be counted for vault_0 (where validator is)
        expected = {
            VaultAddresses.VAULT_0: 36_834_904_184_000_000_000,  # includes pending deposit
            VaultAddresses.VAULT_1: 0,
            VaultAddresses.VAULT_2: 2_000_900_000_000_000_000,
            VaultAddresses.VAULT_3: 1_000_000_000_000_000_000,
        }
        assert result == expected

    def test_multiple_pending_deposits_for_same_validator(self, web3, default_vaults_map):
        # Setup
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

        configure_validator_statuses(web3, {})
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(
            vaults=default_vaults_map,
            validators=validators,
            pending_deposits=pending_deposits,
            block_identifier="latest",
        )

        # Assert
        expected = {
            VaultAddresses.VAULT_0: 1_000_000_000_000_000_000,
            VaultAddresses.VAULT_1: 35_000_000_000_000_000_000,  # 32 ETH + 3 pending
            VaultAddresses.VAULT_2: 2_000_900_000_000_000_000,
            VaultAddresses.VAULT_3: 1_000_000_000_000_000_000,
        }
        assert result == expected

    def test_pending_deposit_without_validator_counts_predeposit(self, web3, default_vaults_map):
        # Setup
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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, pending_deposits)

        # Assert
        expected = {
            VaultAddresses.VAULT_0: 2_000_000_000_000_000_000,
            VaultAddresses.VAULT_1: 0,
            VaultAddresses.VAULT_2: 2_000_900_000_000_000_000,
            VaultAddresses.VAULT_3: 1_000_000_000_000_000_000,
        }
        assert result == expected


@pytest.mark.unit
class TestGetVaultsTotalValuesWithValidatorStatuses:

    def test_predeposited_validator_counts_1_eth(self, web3, default_vaults_map):
        # Setup
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb' '7b476d9b5e418fea99002'

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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        # Assert
        expected_vault_0 = default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance + gwei_to_wei(
            Gwei(1_000_000_000)
        )
        assert result[VaultAddresses.VAULT_0] == expected_vault_0

    def test_activated_validator_counts_full_balance_plus_pending(self, web3, default_vaults_map):
        # Setup
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb' '7b476d9b5e418fea99005'

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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, pending_deposits)

        # Assert
        expected_vault_0 = (
            default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance
            + gwei_to_wei(Gwei(1_000_000_000))
            + gwei_to_wei(Gwei(31_000_000_000))
        )
        assert result[VaultAddresses.VAULT_0] == expected_vault_0

    def test_proven_validator_not_counted(self, web3, default_vaults_map):
        # Setup
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb' '7b476d9b5e418fea99003'

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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        # Assert
        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance

    def test_predeposited_validator_with_pending_deposit_no_double_count(self, web3, default_vaults_map):
        # Setup
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb' '7b476d9b5e418fea99001'

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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, pending_deposits)

        # Assert
        expected_vault_0 = default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance + gwei_to_wei(
            Gwei(1_000_000_000)
        )
        assert result[VaultAddresses.VAULT_0] == expected_vault_0

    def test_doppelganger_pubkey_not_counted(self, web3, default_vaults_map):
        # Setup
        pubkey = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb' '7b476d9b5e418fea99001'

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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        # Assert
        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance
        assert result[VaultAddresses.VAULT_1] == default_vaults_map[VaultAddresses.VAULT_1].aggregated_balance


@pytest.mark.unit
class TestGetVaultsTotalValuesEdgeCases:

    def test_unmatched_pending_deposit_non_predeposited_stage_ignored(self, web3, default_vaults_map):
        # Setup
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

        configure_validator_statuses(web3, validator_statuses)
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, [], pending_deposits)

        # Assert
        # No extra 1 ETH should be counted because stage is not PREDEPOSITED.
        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance

    def test_far_future_validator_without_status_skipped(self, web3, default_vaults_map):
        # Setup
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
        configure_validator_statuses(web3, {})
        service = StakingVaultsService(web3)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, validators, [])

        # Assert
        # Validator should be ignored entirely.
        assert result[VaultAddresses.VAULT_0] == default_vaults_map[VaultAddresses.VAULT_0].aggregated_balance


@pytest.mark.unit
class TestGetVaultsTotalValuesDefaults:

    def test_defaults_and_logging(self, web3, monkeypatch, default_vaults_map):
        # Setup
        service = StakingVaultsService(web3)

        logger_mock = MagicMock()
        monkeypatch.setattr("src.services.staking_vaults.logger", logger_mock)

        service._get_validators_by_vault = MagicMock(return_value={})
        service._get_total_pending_amount_by_pubkey = MagicMock(return_value={})
        service._get_non_eligible_for_activation_validators_pubkeys = MagicMock(return_value=set())
        service._get_pubkey_statuses_by_vault = MagicMock(return_value={})
        service._get_unmatched_deposits_pubkeys = MagicMock(return_value=set())
        service._calculate_vault_total_value = MagicMock(return_value=123)

        # Act
        result = service.get_vaults_total_values(default_vaults_map, [], [])

        # Assert
        service._get_pubkey_statuses_by_vault.assert_has_calls(
            [call(pubkeys=ANY, block_identifier="latest"), call(pubkeys=ANY, block_identifier="latest")],
            any_order=False,
        )

        assert all(value == 123 for value in result.values())
        assert logger_mock.info.call_count == len(default_vaults_map)
        logger_mock.info.assert_has_calls(
            [
                call({"msg": f"Calculate vault TVL: {vault_address}.", "value": 123})
                for vault_address in default_vaults_map
            ],
            any_order=False,
        )


@pytest.mark.unit
class TestCalculateVaultTotalValue:

    def test_mixed_validators_and_unmatched_pending(self):
        # Setup
        vault_balance = gwei_to_wei(Gwei(10_000_000_000))

        eligible_validator = ValidatorFactory.build(
            balance=Gwei(2_000_000_000),
            validator=ValidatorStateFactory.build(
                pubkey=TestPubkeys.PUBKEY_0,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        )
        predeposited_validator = ValidatorFactory.build(
            balance=Gwei(5_000_000_000),
            validator=ValidatorStateFactory.build_not_eligible_for_activation(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        )
        activated_validator = ValidatorFactory.build(
            balance=Gwei(1_000_000_000),
            validator=ValidatorStateFactory.build_not_eligible_for_activation(
                pubkey=TestPubkeys.PUBKEY_2,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        )
        missing_status_validator = ValidatorFactory.build(
            balance=Gwei(7_000_000_000),
            validator=ValidatorStateFactory.build_not_eligible_for_activation(
                pubkey=TestPubkeys.PUBKEY_3,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        )

        total_pending_amount_by_pubkey = {
            TestPubkeys.PUBKEY_0: Gwei(1_000_000_000),
            TestPubkeys.PUBKEY_2: Gwei(31_000_000_000),
        }

        vault_validator_statuses = {
            TestPubkeys.PUBKEY_1: ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0),
            TestPubkeys.PUBKEY_2: ValidatorStatusFactory.build_activated(VaultAddresses.VAULT_0),
        }

        vault_unmatched_pending_deposit_statuses = {
            "0xaaa": ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0),
            "0xbbb": ValidatorStatusFactory.build(stage=ValidatorStage.PROVEN, staking_vault=VaultAddresses.VAULT_0),
        }

        # Act
        result = StakingVaultsService._calculate_vault_total_value(
            vault_aggregated_balance=vault_balance,
            vault_validators=[
                eligible_validator,
                predeposited_validator,
                activated_validator,
                missing_status_validator,
            ],
            total_pending_amount_by_pubkey=total_pending_amount_by_pubkey,
            vault_validator_statuses=vault_validator_statuses,
            vault_unmatched_pending_deposit_statuses=vault_unmatched_pending_deposit_statuses,
        )

        # Assert
        eligible_total = gwei_to_wei(Gwei(3_000_000_000))
        activated_total = gwei_to_wei(Gwei(32_000_000_000))
        expected = (
            vault_balance
            + eligible_total
            + int(gwei_to_wei(Gwei(1_000_000_000)))
            + activated_total
            + int(gwei_to_wei(Gwei(1_000_000_000)))
        )

        assert result == expected

    def test_missing_status_does_not_stop_processing(self):
        # Setup
        vault_balance = gwei_to_wei(Gwei(0))

        missing_status_validator = ValidatorFactory.build(
            balance=Gwei(2_000_000_000),
            validator=ValidatorStateFactory.build_not_eligible_for_activation(
                pubkey=TestPubkeys.PUBKEY_0,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        )
        predeposited_validator = ValidatorFactory.build(
            balance=Gwei(1_000_000_000),
            validator=ValidatorStateFactory.build_not_eligible_for_activation(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        )

        vault_validator_statuses = {
            TestPubkeys.PUBKEY_1: ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0),
        }

        # Act
        result = StakingVaultsService._calculate_vault_total_value(
            vault_aggregated_balance=vault_balance,
            vault_validators=[missing_status_validator, predeposited_validator],
            total_pending_amount_by_pubkey={},
            vault_validator_statuses=vault_validator_statuses,
            vault_unmatched_pending_deposit_statuses={},
        )

        # Assert
        assert result == int(gwei_to_wei(MIN_DEPOSIT_AMOUNT))
