from decimal import Decimal

import pytest

from src.modules.accounting.types import SECONDS_IN_YEAR
from src.utils.apr import calculate_steth_apr

pytestmark = pytest.mark.unit


class TestCalculateStethAprRay:
    """Test cases for calculate_steth_apr function."""

    def test_zero_pre_total_shares_raises_error(self):
        """Test that zero pre_total_shares raises ValueError."""
        with pytest.raises(ValueError, match="Cannot compute APR: zero division risk."):
            calculate_steth_apr(0, 1000, 1000, 1100, SECONDS_IN_YEAR)

    def test_zero_post_total_shares_raises_error(self):
        """Test that zero post_total_shares raises ValueError."""
        with pytest.raises(ValueError, match="Cannot compute APR: zero division risk."):
            calculate_steth_apr(1000, 1000, 0, 1100, SECONDS_IN_YEAR)

    def test_zero_time_elapsed_raises_error(self):
        """Test that zero time_elapsed raises ValueError."""
        with pytest.raises(ValueError, match="Cannot compute APR. time_elapsed is 0"):
            calculate_steth_apr(1000, 1000, 1000, 1100, 0)

    def test_basic_apr_calculation(self):
        """Test basic APR calculation with simple values."""
        pre_total_shares = 1000
        pre_total_ether = 1000
        post_total_shares = 1000
        post_total_ether = 1100
        time_elapsed = SECONDS_IN_YEAR

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0.1")

    def test_zero_growth_apr(self):
        """Test APR calculation when there's no growth."""
        pre_total_shares = 1000
        pre_total_ether = 1000
        post_total_shares = 1000
        post_total_ether = 1000  # No change
        time_elapsed = SECONDS_IN_YEAR

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0")

    def test_negative_growth_apr(self):
        """Test APR calculation when there's negative growth (loss)."""
        pre_total_shares = 1000
        pre_total_ether = 1000
        post_total_shares = 1000
        post_total_ether = 900  # 10% decrease
        time_elapsed = SECONDS_IN_YEAR

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0")

    def test_large_numbers_precision(self):
        """Test APR calculation with high precision values."""
        pre_total_shares = 10**27
        pre_total_ether = 10**27
        post_total_shares = 10**27
        post_total_ether = 10**27 + 5 * 10**25  # 5% increase
        time_elapsed = SECONDS_IN_YEAR

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0.05")

    def test_small_changes_precision(self):
        """Test APR calculation with small changes to ensure precision."""
        pre_total_shares = 10**18
        pre_total_ether = 10**18
        post_total_shares = 10**18
        post_total_ether = 10**18 + 10
        time_elapsed = SECONDS_IN_YEAR

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0.00000000000000001")

    def test_half_year_calculation(self):
        """Test APR calculation for a half year period."""
        pre_total_shares = 1000
        pre_total_ether = 1000
        post_total_shares = 1000
        post_total_ether = 1100
        time_elapsed = SECONDS_IN_YEAR // 2

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0.2")

    def test_share_rate_change_with_constant_ether(self):
        """Test APR calculation when shares change but ether stays constant."""
        pre_total_shares = 1000
        pre_total_ether = 1000
        post_total_shares = 900  # Shares decreased
        post_total_ether = 1000  # Ether stayed the same
        time_elapsed = SECONDS_IN_YEAR

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0.111111111111111111111111110")

    def test_very_small_time_period(self):
        """Test APR calculation for a very small time period."""
        pre_total_shares = 10**27
        pre_total_ether = 10**27
        post_total_shares = 10**27
        post_total_ether = 10**27 + 10**24
        time_elapsed = 3600

        apr = calculate_steth_apr(pre_total_shares, pre_total_ether, post_total_shares, post_total_ether, time_elapsed)

        assert apr == Decimal("0.001") * Decimal(SECONDS_IN_YEAR) / Decimal("3600")

    @pytest.mark.parametrize(
        "pre_shares, pre_ether, post_shares, post_ether, time_elapsed, expected_apr",
        [
            # Test case 1: 5% annual growth
            (10**27, 10**27, 10**27, 10**27 + 5 * 10**25, SECONDS_IN_YEAR, Decimal("0.05")),
            # Test case 2: 20% annual growth
            (10**27, 10**27, 10**27, 10**27 + 2 * 10**26, SECONDS_IN_YEAR, Decimal("0.2")),
            # Test case 3: 1% annual growth
            (10**27, 10**27, 10**27, 10**27 + 10**25, SECONDS_IN_YEAR, Decimal("0.01")),
            # Test case 4: 50% annual growth
            (10**27, 10**27, 10**27, 10**27 + 5 * 10**26, SECONDS_IN_YEAR, Decimal("0.5")),
            # Test case 5: 100% annual growth
            (10**27, 10**27, 10**27, 2 * 10**27, SECONDS_IN_YEAR, Decimal("1.0")),
        ],
    )
    def test_various_growth_rates(self, pre_shares, pre_ether, post_shares, post_ether, time_elapsed, expected_apr):
        """Test APR calculation with various growth rates."""
        apr = calculate_steth_apr(pre_shares, pre_ether, post_shares, post_ether, time_elapsed)
        assert apr == expected_apr
