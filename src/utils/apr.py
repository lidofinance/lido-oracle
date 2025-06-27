from src.constants import WEI_PRECISION
from src.modules.accounting.types import SECONDS_IN_YEAR
from decimal import Decimal, localcontext

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

    if pre_total_shares == 0 or time_elapsed_seconds == 0 or post_total_shares == 0:
        raise ValueError("Cannot compute APR: zero division risk.")

    with localcontext() as ctx:
        ctx.prec = WEI_PRECISION

        pre_rate = Decimal(pre_total_ether) / Decimal(pre_total_shares)
        post_rate = Decimal(post_total_ether) / Decimal(post_total_shares)

        rate_diff: Decimal = post_rate - pre_rate

        if time_elapsed_seconds == 0:
            raise ValueError("Cannot compute APR. time_elapsed is 0")

        return (rate_diff * Decimal(SECONDS_IN_YEAR)) / (pre_rate * Decimal(time_elapsed_seconds))

def get_steth_by_shares(shares: int, pre_total_ether: int, pre_total_shares: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = WEI_PRECISION
        return (Decimal(shares) * Decimal(pre_total_ether)) / Decimal(pre_total_shares)
