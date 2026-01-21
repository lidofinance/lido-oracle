from decimal import Decimal

import pytest

from src.services.staking_vaults import StakingVaultsService
from tests.modules.accounting.staking_vault.conftest import FeeTestConstants


class TestCalcFeeValue:
    """Tests for calc_fee_value static method."""

    @pytest.mark.unit
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
    def test_infra_fee_calculation(self, vault_total_value, time_elapsed_seconds, core_apr_ratio, fee_bp, expected):
        """Verifies infrastructure fees are correctly calculated based on vault total value,
        elapsed time, core APR ratio, and fee basis points. Ensures fees charged on total
        vault value are computed accurately for proper fee distribution.
        """
        result = StakingVaultsService.calc_fee_value(
            Decimal(vault_total_value), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.unit
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
    def test_reservation_fee_calculation(self, mintable_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected):
        """Verifies reservation liquidity fees are correctly calculated based on mintable
        stETH amount (reserved liquidity), elapsed time, and fee basis points. Ensures
        opportunity cost of reserved funds is accurately reflected in fee calculations.
        """
        result = StakingVaultsService.calc_fee_value(
            Decimal(mintable_steth), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected

    @pytest.mark.unit
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
    def test_liquidity_fee_calculation(self, minted_steth, time_elapsed_seconds, core_apr_ratio, fee_bp, expected):
        """Verifies liquidity fees are correctly calculated based on minted stETH amount
        (actual liquidity provided), elapsed time, and fee basis points. Ensures liquidity
        providers are compensated accurately based on actual minted amounts and holding duration.
        """
        result = StakingVaultsService.calc_fee_value(
            Decimal(minted_steth), time_elapsed_seconds, Decimal(str(core_apr_ratio)), fee_bp
        )
        assert result == expected
