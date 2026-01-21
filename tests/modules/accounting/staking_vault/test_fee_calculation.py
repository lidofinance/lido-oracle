from decimal import Decimal

import pytest

from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import FeeTestConstants

# =============================================================================
# Tests
# =============================================================================


@pytest.mark.unit
class TestCalcFeeValue:

    @pytest.mark.parametrize(
        'vault_total_value, time_elapsed_seconds, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.VAULT_TOTAL_VALUE,
                7_200 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.INFRA_FEE_BP,
                Decimal('2905190375124446.25388535346'),
            ),
            (
                FeeTestConstants.VAULT_TOTAL_VALUE,
                7_200 * 364 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.INFRA_FEE_BP,
                Decimal('1057489296545298436.41426866'),
            ),
        ],
    )
    def test_calc_fee_value__infra_fee__returns_expected_fee(
        self, vault_total_value, time_elapsed_seconds, core_apr_ratio, fee_bp, expected
    ):
        result = StakingVaultsService.calc_fee_value(
            Decimal(vault_total_value), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.parametrize(
        'mintable_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.RESERVATION_FEE_BP,
                Decimal('7262975937811115.63471338365'),
            ),
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * 364 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.RESERVATION_FEE_BP,
                Decimal('2643723241363246091.03567165'),
            ),
        ],
    )
    def test_calc_fee_value__reservation_fee__returns_expected_fee(
        self, mintable_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected
    ):
        result = StakingVaultsService.calc_fee_value(
            Decimal(mintable_steth), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.parametrize(
        'minted_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected',
        [
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.LIQUIDITY_FEE_BP,
                Decimal('18883737438308900.6502547975'),
            ),
            (
                FeeTestConstants.MINTABLE_STETH,
                7_200 * 364 * FeeTestConstants.SECONDS_PER_SLOT,
                FeeTestConstants.CORE_APR_RATIO,
                FeeTestConstants.LIQUIDITY_FEE_BP,
                Decimal('6873680427544439836.69274631'),
            ),
        ],
    )
    def test_calc_fee_value__liquidity_fee__returns_expected_fee(
        self, minted_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected
    ):
        result = StakingVaultsService.calc_fee_value(
            Decimal(minted_steth), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected
