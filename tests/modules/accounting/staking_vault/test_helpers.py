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


@pytest.mark.unit
class TestPendingDepositHelpers:
    """Tests for pending deposit helper methods."""

    def test_get_total_pending_amount_by_pubkey(self):
        """Verifies that pending deposit amounts are correctly aggregated per pubkey.
        Ensures multiple pending deposits for the same validator are summed together.
        """
        pending = [
            PendingDepositFactory.build(pubkey=TestPubkeys.PUBKEY_0, amount=Gwei(1_000)),
            PendingDepositFactory.build(pubkey=TestPubkeys.PUBKEY_0, amount=Gwei(2_000)),
            PendingDepositFactory.build(pubkey=TestPubkeys.PUBKEY_1, amount=Gwei(3_000)),
        ]

        result = StakingVaultsService._get_total_pending_amount_by_pubkey(pending)

        assert result[TestPubkeys.PUBKEY_0] == Gwei(3_000)
        assert result[TestPubkeys.PUBKEY_1] == Gwei(3_000)


@pytest.mark.unit
class TestValidatorFilteringHelpers:
    """Tests for validator filtering helper methods."""

    def test_get_non_eligible_for_activation_pubkeys(self):
        """Verifies that only far-future validators (not eligible for activation)
        belonging to tracked vault withdrawal credentials are returned. Ensures eligible
        validators and validators from other vaults are filtered out.
        """
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

        result = StakingVaultsService._get_non_eligible_for_activation_validators_pubkeys(
            validators, {WithdrawalCredentials.WC_0}
        )

        assert result == {TestPubkeys.PUBKEY_0}

    def test_get_unmatched_deposits_pubkeys(self):
        """Verifies that pending deposits without matching validators are correctly
        detected and returned. Ensures only deposits with tracked withdrawal credentials
        are included in the result.
        """
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

        result = StakingVaultsService._get_unmatched_deposits_pubkeys(validators, pending, {WithdrawalCredentials.WC_0})

        assert result == {TestPubkeys.PUBKEY_2}


@pytest.mark.unit
class TestStatusFetchingHelpers:
    """Tests for validator status fetching helper."""

    def test_get_pubkey_statuses_by_vault_groups_statuses(self):
        """Verifies that validator statuses are correctly grouped by their staking
        vault addresses. Ensures status retrieval and grouping works correctly for
        multiple validators across different vaults.
        """
        status_vault_0 = ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_0)
        status_vault_1 = ValidatorStatusFactory.build_predeposited(VaultAddresses.VAULT_1)

        w3_mock = MagicMock()
        lazy_oracle = MagicMock()
        lazy_oracle.get_validator_statuses.return_value = {
            TestPubkeys.PUBKEY_0: status_vault_0,
            TestPubkeys.PUBKEY_1: status_vault_1,
        }
        w3_mock.lido_contracts.lazy_oracle = lazy_oracle

        service = StakingVaultsService(w3_mock)

        result = service._get_pubkey_statuses_by_vault(
            {TestPubkeys.PUBKEY_0, TestPubkeys.PUBKEY_1}, block_identifier='latest'
        )

        assert result == {
            VaultAddresses.VAULT_0: {TestPubkeys.PUBKEY_0: status_vault_0},
            VaultAddresses.VAULT_1: {TestPubkeys.PUBKEY_1: status_vault_1},
        }
