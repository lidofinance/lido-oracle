from src.constants import TOTAL_BASIS_POINTS
from src.modules.accounting.types import SECONDS_IN_YEAR
from decimal import Decimal

def calculate_steth_apr(
        pre_total_shares: int,
        pre_total_ether: int,
        post_total_shares: int,
        post_total_ether: int,
        time_elapsed_seconds: int,
) -> Decimal:
    """
    Compute user-facing APR using share rate growth over time.
    Formula follows Lido V2-style:
        apr = (postRate - preRate) * SECONDS_IN_YEAR / preRate / timeElapsed
    """

    if pre_total_shares == 0 or post_total_shares == 0:
        raise ValueError("Cannot compute APR: zero division risk.")

    if time_elapsed_seconds == 0:
        raise ValueError("Cannot compute APR. time_elapsed is 0")

    pre_rate = Decimal(pre_total_ether) / Decimal(pre_total_shares)
    post_rate = Decimal(post_total_ether) / Decimal(post_total_shares)

    rate_diff: Decimal = post_rate - pre_rate

    return (rate_diff * Decimal(SECONDS_IN_YEAR)) / (pre_rate * Decimal(time_elapsed_seconds))

def get_steth_by_shares(shares: int, total_ether: int, total_shares: int) -> Decimal:
    return (Decimal(shares) * Decimal(total_ether)) / Decimal(total_shares)

def get_core_apr_ratio(
        pre_total_shares: int,
        pre_total_pooled_ether: int,
        post_total_shares: int,
        post_total_pooled_ether: int,
        lido_fee_bp: Decimal,
        time_elapsed_seconds: int
) -> Decimal:
    if lido_fee_bp == 0:
        return Decimal(0)

    steth_apr_ratio = calculate_steth_apr(
            pre_total_shares=pre_total_shares,
            pre_total_ether=pre_total_pooled_ether,
            post_total_shares=post_total_shares,
            post_total_ether=post_total_pooled_ether,
            time_elapsed_seconds=time_elapsed_seconds,
    )

    total_basis_points_dec = Decimal(TOTAL_BASIS_POINTS)
    return steth_apr_ratio * total_basis_points_dec / (total_basis_points_dec - lido_fee_bp)
