from decimal import Decimal

from src.modules.accounting.types import SECONDS_IN_YEAR


def calculate_steth_apr(
    pre_total_shares: int,
    pre_total_ether: int,
    post_total_shares: int,
    post_total_ether: int,
    time_elapsed: int,
) -> Decimal:
    """
    Compute user-facing APR using share rate growth over time.
    Formula follows Lido V2-style:
        apr = (postRate - preRate) * SECONDS_IN_YEAR / preRate / timeElapsed
    """

    if pre_total_shares == 0 or time_elapsed == 0 or post_total_shares == 0:
        raise ValueError("Cannot compute APR: zero division risk.")

    pre_rate = Decimal(pre_total_ether) / Decimal(pre_total_shares)
    post_rate = Decimal(post_total_ether) / Decimal(post_total_shares)

    rate_diff = post_rate - pre_rate

    if time_elapsed == 0:
        raise ValueError("Cannot compute APR. time_elapsed is 0")

    return (rate_diff * Decimal(SECONDS_IN_YEAR)) / (pre_rate * Decimal(time_elapsed))
