from unittest.mock import MagicMock

import pytest

from src.services.staking_vaults import StakingVaultsService
from src.types import Gwei
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
# Tests
# =============================================================================


@pytest.mark.unit
class TestPendingDepositHelpers:

    def test_get_total_pending_amount_by_pubkey(self):
        # Setup
        pending = [
            PendingDepositFactory.build(pubkey=TestPubkeys.PUBKEY_0, amount=Gwei(1_000)),
            PendingDepositFactory.build(pubkey=TestPubkeys.PUBKEY_0, amount=Gwei(2_000)),
            PendingDepositFactory.build(pubkey=TestPubkeys.PUBKEY_1, amount=Gwei(3_000)),
        ]

        # Act
        result = StakingVaultsService._get_total_pending_amount_by_pubkey(pending)

        # Assert
        assert result[TestPubkeys.PUBKEY_0] == Gwei(3_000)
        assert result[TestPubkeys.PUBKEY_1] == Gwei(3_000)


@pytest.mark.unit
class TestValidatorFilteringHelpers:

    def test_get_non_eligible_for_activation_pubkeys(self):
        # Setup
        validators = [
            ValidatorFactory.build(
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                )
            ),
            # Eligible validator – should be ignored
            ValidatorFactory.build(
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_1,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                )
            ),
            # Far-future but WC not in vault set
            ValidatorFactory.build(
                validator=ValidatorStateFactory.build_not_eligible_for_activation(
                    pubkey=TestPubkeys.PUBKEY_2,
                    withdrawal_credentials='0xdeadbeef',
                )
            ),
        ]

        # Act
        result = StakingVaultsService._get_non_eligible_for_activation_validators_pubkeys(
            validators, {WithdrawalCredentials.WC_0}
        )

        # Assert
        assert result == {TestPubkeys.PUBKEY_0}

    def test_get_unmatched_deposits_pubkeys(self):
        # Setup
        validators = [
            ValidatorFactory.build(
                validator=ValidatorStateFactory.build(
                    pubkey=TestPubkeys.PUBKEY_0,
                    withdrawal_credentials=WithdrawalCredentials.WC_0,
                )
            )
        ]

        pending = [
            # Matched pubkey – excluded
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_0,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
            # Unmatched but WC not tracked – excluded
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_1,
                withdrawal_credentials='0xdeadbeef',
            ),
            # Unmatched and WC tracked – should be returned
            PendingDepositFactory.build(
                pubkey=TestPubkeys.PUBKEY_2,
                withdrawal_credentials=WithdrawalCredentials.WC_0,
            ),
        ]

        # Act
        result = StakingVaultsService._get_unmatched_deposits_pubkeys(validators, pending, {WithdrawalCredentials.WC_0})

        # Assert
        assert result == {TestPubkeys.PUBKEY_2}


@pytest.mark.unit
class TestStatusFetchingHelpers:

    def test_get_pubkey_statuses_by_vault_groups_statuses(self, web3):
        # Setup
        status_vault_0 = ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0)
        status_vault_1 = ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_1)

        lazy_oracle = MagicMock()
        lazy_oracle.get_validator_statuses.return_value = {
            TestPubkeys.PUBKEY_0: status_vault_0,
            TestPubkeys.PUBKEY_1: status_vault_1,
        }
        web3.lido_contracts.lazy_oracle = lazy_oracle

        service = StakingVaultsService(web3)

        # Act
        result = service._get_pubkey_statuses_by_vault(
            {TestPubkeys.PUBKEY_0, TestPubkeys.PUBKEY_1}, block_identifier='latest'
        )

        # Assert
        assert result == {
            VaultAddresses.VAULT_0: {TestPubkeys.PUBKEY_0: status_vault_0},
            VaultAddresses.VAULT_1: {TestPubkeys.PUBKEY_1: status_vault_1},
        }
