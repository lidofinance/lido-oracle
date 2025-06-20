from src.modules.accounting.types import SECONDS_IN_YEAR


def predict_apr(pre_total_shares: int, pre_total_ether: int, post_total_shares: int, post_total_ether: int,
                 time_elapsed: int) -> int:
    """
    https://github.com/lidofinance/lido-eth-api-backend/blob/develop/src/apr/steth/steth-apr.service.ts

    Compute user-facing APR using share rate growth over time.
    Formula follows Lido V2-style:
        apr = (postRate - preRate) * SECONDS_IN_YEAR / preRate / timeElapsed
    """

    if pre_total_shares == 0 or time_elapsed == 0 or post_total_shares == 0:
        raise ValueError("Cannot compute APR: zero division risk.")

    pre_rate = pre_total_ether * 10 ** 27 // pre_total_shares
    post_rate = post_total_ether * 10 ** 27 // post_total_shares

    rate_diff = post_rate - pre_rate
    # if rate_diff == 0:
    #     raise ValueError("Cannot compute APR. rate_diff is 0")

    mul_for_precision = 10_0000

    if time_elapsed == 0:
        raise ValueError("Cannot compute APR. time_elapsed is 0")

    apr = (rate_diff * mul_for_precision * SECONDS_IN_YEAR * 100) / (pre_rate * time_elapsed)

    return apr / mul_for_precision
