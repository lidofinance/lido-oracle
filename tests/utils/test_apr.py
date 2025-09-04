from decimal import Decimal

import pytest

from src.modules.accounting.types import SECONDS_IN_YEAR
from src.utils.apr import calculate_gross_core_apr

pytestmark = pytest.mark.unit


class TestCalculateStethAprRay:
    """Test cases for calculate_steth_apr function."""

    def test_zero_pre_total_shares_raises_error(self):
        """Test that zero pre_total_shares raises ValueError."""
        with pytest.raises(ValueError, match="pre_total_shares == 0"):
            calculate_gross_core_apr(
                post_internal_ether=1100,
                post_internal_shares=1000,
                shares_minted_as_fees=0,
                pre_total_ether=1000,
                pre_total_shares=0,
                time_elapsed_seconds=SECONDS_IN_YEAR,
            )

    def test_post_shares_equal_fees_raises_error(self):
        with pytest.raises(ValueError, match="post_internal_shares == shares_minted_as_fees"):
            calculate_gross_core_apr(
                post_internal_ether=1100,
                post_internal_shares=1000,
                shares_minted_as_fees=1000,
                pre_total_ether=1000,
                pre_total_shares=1000,
                time_elapsed_seconds=SECONDS_IN_YEAR,
            )

    def test_zero_time_elapsed_raises_error(self):
        """Test that zero post_total_shares raises ValueError."""
        with pytest.raises(ValueError, match="time_elapsed is 0"):
            calculate_gross_core_apr(
                post_internal_ether=1100,
                post_internal_shares=1000,
                shares_minted_as_fees=0,
                pre_total_ether=1000,
                pre_total_shares=1000,
                time_elapsed_seconds=0,
            )

    def test_basic_apr_calculation(self):
        """Test basic APR calculation with simple values."""
        apr = calculate_gross_core_apr(
            post_internal_ether=1100,
            post_internal_shares=1000,
            shares_minted_as_fees=0,
            pre_total_ether=1000,
            pre_total_shares=1000,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )

        assert apr == Decimal("0.1")

    def test_zero_growth_apr(self):
        """Test APR calculation when there's no growth."""
        apr = calculate_gross_core_apr(
            post_internal_ether=1000,
            post_internal_shares=1000,
            shares_minted_as_fees=0,
            pre_total_ether=1000,
            pre_total_shares=1000,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )

        assert apr == Decimal("0")

    def test_negative_growth_apr(self):
        """Test APR calculation when there's negative growth (loss)."""
        apr = calculate_gross_core_apr(
            post_internal_ether=900,  # decreased pool on 10%
            post_internal_shares=1000,
            shares_minted_as_fees=0,
            pre_total_ether=1000,
            pre_total_shares=1000,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )

        assert apr == Decimal("0")

    def test_large_numbers_precision(self):
        """Test APR calculation with high precision values."""
        apr = calculate_gross_core_apr(
            post_internal_ether=10**27 + 5 * 10**25,  # increased на 5%
            post_internal_shares=10**27,
            shares_minted_as_fees=0,
            pre_total_ether=10**27,
            pre_total_shares=10**27,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )

        assert apr == Decimal("0.05")

    def test_small_changes_precision(self):
        """Test APR calculation with small changes to ensure precision."""
        apr = calculate_gross_core_apr(
            post_internal_ether=10**18 + 10,
            post_internal_shares=10**18,
            shares_minted_as_fees=0,
            pre_total_ether=10**18,
            pre_total_shares=10**18,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )

        assert apr == Decimal("0.00000000000000001")

    def test_half_year_calculation(self):
        """Test APR calculation for a half year period."""
        apr = calculate_gross_core_apr(
            post_internal_ether=1100,
            post_internal_shares=1000,
            shares_minted_as_fees=0,
            pre_total_ether=1000,
            pre_total_shares=1000,
            time_elapsed_seconds=SECONDS_IN_YEAR // 2,
        )

        assert apr == Decimal("0.2")

    def test_share_rate_change_with_constant_ether(self):
        """Test APR calculation when shares change but ether stays constant."""
        apr = calculate_gross_core_apr(
            post_internal_ether=1000,  # Ether stayed the same
            post_internal_shares=900,  # Shares decreased
            shares_minted_as_fees=0,
            pre_total_ether=1000,
            pre_total_shares=1000,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )

        assert apr == Decimal("0.111111111111111111111111110")

    def test_very_small_time_period(self):
        """Test APR calculation for a very small time period."""
        apr = calculate_gross_core_apr(
            post_internal_ether=10**27 + 10**24,
            post_internal_shares=10**27,
            shares_minted_as_fees=0,
            pre_total_ether=10**27,
            pre_total_shares=10**27,
            time_elapsed_seconds=3600,
        )

        assert apr == Decimal("0.001") * Decimal(SECONDS_IN_YEAR) / Decimal("3600")

    import pytest
    from decimal import Decimal

    @pytest.mark.parametrize(
        "pre_ether, post_ether, expected_apr",
        [
            # Test case 1: 5% annual growth
            (10**27, 10**27 + 5 * 10**25, Decimal("0.05")),
            # Test case 2: 20% annual growth
            (10**27, 10**27 + 2 * 10**26, Decimal("0.2")),
            # Test case 3: 1% annual growth
            (10**27, 10**27 + 10**25, Decimal("0.01")),
            # Test case 4: 50% annual growth
            (10**27, 10**27 + 5 * 10**26, Decimal("0.5")),
            # Test case 5: 100% annual growth
            (10**27, 2 * 10**27, Decimal("1.0")),
        ],
    )
    def test_various_growth_rates(self, pre_ether, post_ether, expected_apr):
        """Test APR calculation with various growth rates."""
        apr = calculate_gross_core_apr(
            post_internal_ether=post_ether,
            post_internal_shares=10**27,
            shares_minted_as_fees=0,
            pre_total_ether=pre_ether,
            pre_total_shares=10**27,
            time_elapsed_seconds=SECONDS_IN_YEAR,
        )
        assert apr == expected_apr
