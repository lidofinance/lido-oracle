"""
Fixtures and factories for staking vault tests.

This module provides reusable test data builders and pytest fixtures
for testing the StakingVaultsService.
"""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber, ChecksumAddress, HexAddress, HexStr
from faker import Faker
from hexbytes import HexBytes
from web3.types import Wei

from src.constants import FAR_FUTURE_EPOCH
from src.modules.accounting.events import (
    BadDebtSocializedEvent,
    BadDebtWrittenOffToBeInternalizedEvent,
    BurnedSharesOnVaultEvent,
    MintedSharesOnVaultEvent,
    VaultConnectedEvent,
    VaultFeesUpdatedEvent,
    VaultRebalancedEvent,
)
from src.modules.accounting.types import (
    ExtraValue,
    MerkleValue,
    OnChainIpfsVaultReportData,
    ValidatorStage,
    ValidatorStatus,
    VaultFee,
    VaultInfo,
)
from src.providers.consensus.types import PendingDeposit, Validator, ValidatorState
from src.services.staking_vaults import StakingVaultsService
from src.types import EpochNumber, Gwei, SlotNumber, ValidatorIndex
from tests.factory.web3_factory import Web3DataclassFactory

faker = Faker()

# =============================================================================
# Test Constants
# =============================================================================


class VaultAddresses:
    """Pre-defined vault addresses for consistent test data."""

    VAULT_0 = ChecksumAddress(HexAddress(HexStr('0xE312f1ed35c4dBd010A332118baAD69d45A0E302')))
    VAULT_1 = ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC')))
    VAULT_2 = ChecksumAddress(HexAddress(HexStr('0x20d34FD0482E3BdC944952D0277A306860be0014')))
    VAULT_3 = ChecksumAddress(HexAddress(HexStr('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4')))


class WithdrawalCredentials:
    """Pre-defined withdrawal credentials for vaults."""

    WC_0 = '0x020000000000000000000000e312f1ed35c4dbd010a332118baad69d45a0e302'
    WC_1 = '0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc'
    WC_2 = '0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014'
    WC_3 = '0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4'


class TestPubkeys:
    """Pre-defined validator pubkeys for tests."""

    PUBKEY_0 = '0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99124'
    PUBKEY_1 = '0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce'
    PUBKEY_2 = '0x8c96ad1b9a1acf4a898009d96293d191ab911b535cd1e6618e76897b5fa239a7078f1fbf9de8dd07a61a51b137c74a87'
    PUBKEY_3 = '0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307c1'


# Fee calculation test constants
class FeeTestConstants:
    """Constants used in fee calculation tests."""

    PRE_TOTAL_SHARES = 7598409496266444487755575
    PRE_TOTAL_POOLED_ETHER = Wei(9165134090291140983725643)
    CORE_APR_RATIO = Decimal('0.03316002451606887481973829228')
    LIABILITY_SHARES = 2880 * 10**18
    SECONDS_PER_SLOT = 12
    RESERVE_RATIO_BP = 2000
    INFRA_FEE_BP = 100
    LIQUIDITY_FEE_BP = 650
    RESERVATION_FEE_BP = 250
    MINTABLE_STETH = 3200 * 10**18
    VAULT_TOTAL_VALUE = 3200 * 10**18
    BLOCKS_PER_FRAME = 7_200


# =============================================================================
# Factory Classes
# =============================================================================


class ValidatorStateFactory(Web3DataclassFactory[ValidatorState]):
    """Factory for creating ValidatorState objects."""

    __set_as_default_factory_for_type__ = True
    withdrawal_credentials = WithdrawalCredentials.WC_0
    effective_balance = Gwei(32_000_000_000)
    slashed = False
    exit_epoch = FAR_FUTURE_EPOCH
    withdrawable_epoch = FAR_FUTURE_EPOCH

    @classmethod
    def build(cls, **kwargs: Any) -> ValidatorState:
        kwargs.setdefault('pubkey', HexBytes(faker.binary(48)).hex())
        kwargs.setdefault('activation_eligibility_epoch', EpochNumber(225469))
        kwargs.setdefault('activation_epoch', EpochNumber(225475))
        return super().build(**kwargs)

    @classmethod
    def build_not_eligible_for_activation(cls, **kwargs: Any) -> ValidatorState:
        """Build a validator that is not yet eligible for activation (FAR_FUTURE_EPOCH)."""
        return cls.build(
            activation_eligibility_epoch=FAR_FUTURE_EPOCH,
            activation_epoch=FAR_FUTURE_EPOCH,
            exit_epoch=FAR_FUTURE_EPOCH,
            withdrawable_epoch=FAR_FUTURE_EPOCH,
            **kwargs,
        )


class ValidatorFactory(Web3DataclassFactory[Validator]):
    """Factory for creating Validator objects."""

    balance = Gwei(32_000_000_000)

    @classmethod
    def build(cls, **kwargs: Any) -> Validator:
        kwargs.setdefault('index', ValidatorIndex(faker.pyint(min_value=1, max_value=10000)))
        return super().build(**kwargs)

    @classmethod
    def build_active(
        cls, withdrawal_credentials: str, balance: Gwei = Gwei(32_000_000_000), **kwargs: Any
    ) -> Validator:
        """Build an active validator with given withdrawal credentials."""
        # Remove 'validator' from kwargs if present to avoid duplicate
        kwargs.pop('validator', None)
        return cls.build(
            balance=balance,
            validator=ValidatorStateFactory.build(
                withdrawal_credentials=withdrawal_credentials,
                effective_balance=Gwei(32_000_000_000),
            ),
            **kwargs,
        )

    @classmethod
    def build_not_eligible(
        cls, withdrawal_credentials: str, balance: Gwei = Gwei(1_000_000_000), **kwargs: Any
    ) -> Validator:
        """Build a validator not yet eligible for activation."""
        # Remove 'validator' from kwargs if present to avoid duplicate
        kwargs.pop('validator', None)
        return cls.build(
            balance=balance,
            validator=ValidatorStateFactory.build_not_eligible_for_activation(
                withdrawal_credentials=withdrawal_credentials,
                effective_balance=balance,
            ),
            **kwargs,
        )


class PendingDepositFactory(Web3DataclassFactory[PendingDeposit]):
    """Factory for creating PendingDeposit objects."""

    amount = Gwei(1_000_000_000)
    slot = SlotNumber(259388)

    @classmethod
    def build(cls, **kwargs: Any) -> PendingDeposit:
        kwargs.setdefault('pubkey', HexBytes(faker.binary(48)).hex())
        kwargs.setdefault('withdrawal_credentials', WithdrawalCredentials.WC_0)
        kwargs.setdefault('signature', HexBytes(faker.binary(96)).hex())
        return super().build(**kwargs)


class VaultInfoFactory(Web3DataclassFactory[VaultInfo]):
    """Factory for creating VaultInfo objects."""

    aggregated_balance = Wei(1_000_000_000_000_000_000)  # 1 ETH
    in_out_delta = Wei(1_000_000_000_000_000_000)
    liability_shares = 0
    max_liability_shares = 0
    mintable_st_eth = 0
    share_limit = 0
    reserve_ratio_bp = 0
    forced_rebalance_threshold_bp = 0
    infra_fee_bp = 0
    liquidity_fee_bp = 0
    reservation_fee_bp = 0
    pending_disconnect = False

    @classmethod
    def build(cls, **kwargs: Any) -> VaultInfo:
        vault = kwargs.get('vault')
        if vault is None:
            vault = ChecksumAddress(HexAddress(HexStr(HexBytes(faker.binary(20)).hex())))
            kwargs['vault'] = vault

        if 'withdrawal_credentials' not in kwargs:
            # Generate WC from vault address (0x02 prefix + padded address)
            vault_hex = vault[2:].lower() if vault.startswith('0x') else vault.lower()
            kwargs['withdrawal_credentials'] = f'0x020000000000000000000000{vault_hex}'

        return super().build(**kwargs)

    @classmethod
    def build_with_fees(
        cls,
        vault: ChecksumAddress,
        infra_fee_bp: int = FeeTestConstants.INFRA_FEE_BP,
        liquidity_fee_bp: int = FeeTestConstants.LIQUIDITY_FEE_BP,
        reservation_fee_bp: int = FeeTestConstants.RESERVATION_FEE_BP,
        **kwargs: Any,
    ) -> VaultInfo:
        """Build a vault with fee configuration."""
        return cls.build(
            vault=vault,
            infra_fee_bp=infra_fee_bp,
            liquidity_fee_bp=liquidity_fee_bp,
            reservation_fee_bp=reservation_fee_bp,
            **kwargs,
        )


class ValidatorStatusFactory(Web3DataclassFactory[ValidatorStatus]):
    """Factory for creating ValidatorStatus objects."""

    stage = ValidatorStage.NONE
    node_operator = '0x0000000000000000000000000000000000000000'

    @classmethod
    def build(cls, **kwargs: Any) -> ValidatorStatus:
        kwargs.setdefault('staking_vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)

    @classmethod
    def build_predeposited(cls, staking_vault: ChecksumAddress, **kwargs: Any) -> ValidatorStatus:
        return cls.build(stage=ValidatorStage.PREDEPOSITED, staking_vault=staking_vault, **kwargs)

    @classmethod
    def build_activated(cls, staking_vault: ChecksumAddress, **kwargs: Any) -> ValidatorStatus:
        return cls.build(stage=ValidatorStage.ACTIVATED, staking_vault=staking_vault, **kwargs)

    @classmethod
    def build_proven(cls, staking_vault: ChecksumAddress, **kwargs: Any) -> ValidatorStatus:
        return cls.build(stage=ValidatorStage.PROVEN, staking_vault=staking_vault, **kwargs)


class VaultFeeFactory(Web3DataclassFactory[VaultFee]):
    """Factory for creating VaultFee objects."""

    infra_fee = 0
    liquidity_fee = 0
    reservation_fee = 0
    prev_fee = 0


# =============================================================================
# Event Factories
# =============================================================================


class MintedSharesEventFactory(Web3DataclassFactory[MintedSharesOnVaultEvent]):
    """Factory for MintedSharesOnVaultEvent."""

    block_number = BlockNumber(3600)
    amount_of_shares = 1_000_000_000
    locked_amount = MagicMock()
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> MintedSharesOnVaultEvent:
        kwargs.setdefault('vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


class BurnedSharesEventFactory(Web3DataclassFactory[BurnedSharesOnVaultEvent]):
    """Factory for BurnedSharesOnVaultEvent."""

    block_number = BlockNumber(3700)
    amount_of_shares = 500_000_000
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> BurnedSharesOnVaultEvent:
        kwargs.setdefault('vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


class VaultFeesUpdatedEventFactory(Web3DataclassFactory[VaultFeesUpdatedEvent]):
    """Factory for VaultFeesUpdatedEvent."""

    block_number = BlockNumber(3200)
    pre_infra_fee_bp = 100
    infra_fee_bp = 150
    pre_liquidity_fee_bp = 400
    liquidity_fee_bp = 650
    pre_reservation_fee_bp = 200
    reservation_fee_bp = 250
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> VaultFeesUpdatedEvent:
        kwargs.setdefault('vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


class VaultRebalancedEventFactory(Web3DataclassFactory[VaultRebalancedEvent]):
    """Factory for VaultRebalancedEvent."""

    block_number = BlockNumber(3601)
    shares_burned = 500_000_000
    ether_withdrawn = MagicMock()
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> VaultRebalancedEvent:
        kwargs.setdefault('vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


class BadDebtSocializedEventFactory(Web3DataclassFactory[BadDebtSocializedEvent]):
    """Factory for BadDebtSocializedEvent."""

    block_number = BlockNumber(3601)
    bad_debt_shares = 400_000
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> BadDebtSocializedEvent:
        kwargs.setdefault('vault_donor', VaultAddresses.VAULT_0)
        kwargs.setdefault('vault_acceptor', VaultAddresses.VAULT_1)
        return super().build(**kwargs)


class BadDebtWrittenOffEventFactory(Web3DataclassFactory[BadDebtWrittenOffToBeInternalizedEvent]):
    """Factory for BadDebtWrittenOffToBeInternalizedEvent."""

    block_number = BlockNumber(3601)
    bad_debt_shares = 400_000
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> BadDebtWrittenOffToBeInternalizedEvent:
        kwargs.setdefault('vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


class VaultConnectedEventFactory(Web3DataclassFactory[VaultConnectedEvent]):
    """Factory for VaultConnectedEvent."""

    block_number = BlockNumber(3501)
    share_limit = MagicMock()
    reserve_ratio_bp = MagicMock()
    forced_rebalance_threshold_bp = MagicMock()
    infra_fee_bp = MagicMock()
    liquidity_fee_bp = MagicMock()
    reservation_fee_bp = MagicMock()
    event = MagicMock()
    log_index = 0
    transaction_index = 0
    address = MagicMock()
    transaction_hash = MagicMock()
    block_hash = MagicMock()

    @classmethod
    def build(cls, **kwargs: Any) -> VaultConnectedEvent:
        kwargs.setdefault('vault', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


# =============================================================================
# IPFS Report Factories
# =============================================================================


class MerkleValueFactory(Web3DataclassFactory[MerkleValue]):
    """Factory for MerkleValue."""

    total_value_wei = Wei(1_000_000_000_000_000_000)
    fee = 0
    liability_shares = 2880 * 10**18
    max_liability_shares = 2880 * 10**18
    slashing_reserve = 0

    @classmethod
    def build(cls, **kwargs: Any) -> MerkleValue:
        kwargs.setdefault('vault_address', VaultAddresses.VAULT_0)
        return super().build(**kwargs)


class ExtraValueFactory(Web3DataclassFactory[ExtraValue]):
    """Factory for ExtraValue."""

    in_out_delta = '0'
    prev_fee = '0'
    infra_fee = '0'
    liquidity_fee = '0'
    reservation_fee = '0'


class OnChainIpfsVaultReportDataFactory(Web3DataclassFactory[OnChainIpfsVaultReportData]):
    """Factory for OnChainIpfsVaultReportData."""

    timestamp = MagicMock()
    ref_slot = MagicMock()
    tree_root = MagicMock()
    report_cid = 'report_cid'


# =============================================================================
# Pytest Fixtures
# =============================================================================


@pytest.fixture
def default_vaults_map() -> dict[ChecksumAddress, VaultInfo]:
    """Create a standard set of 4 test vaults."""
    return {
        VaultAddresses.VAULT_0: VaultInfoFactory.build(
            vault=VaultAddresses.VAULT_0,
            withdrawal_credentials=WithdrawalCredentials.WC_0,
            aggregated_balance=Wei(1_000_000_000_000_000_000),
            in_out_delta=Wei(1_000_000_000_000_000_000),
        ),
        VaultAddresses.VAULT_1: VaultInfoFactory.build(
            vault=VaultAddresses.VAULT_1,
            withdrawal_credentials=WithdrawalCredentials.WC_1,
            aggregated_balance=Wei(0),
            in_out_delta=Wei(2_000_000_000_000_000_000),
            liability_shares=490_000_000_000_000_000,
        ),
        VaultAddresses.VAULT_2: VaultInfoFactory.build(
            vault=VaultAddresses.VAULT_2,
            withdrawal_credentials=WithdrawalCredentials.WC_2,
            aggregated_balance=Wei(2_000_900_000_000_000_000),
            in_out_delta=Wei(2_000_900_000_000_000_000),
            liability_shares=1_200_000_000_000_010_001,
        ),
        VaultAddresses.VAULT_3: VaultInfoFactory.build(
            vault=VaultAddresses.VAULT_3,
            withdrawal_credentials=WithdrawalCredentials.WC_3,
            aggregated_balance=Wei(1_000_000_000_000_000_000),
            in_out_delta=Wei(1_000_000_000_000_000_000),
        ),
    }
