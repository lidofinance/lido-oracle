from decimal import Decimal

from src.constants import SHARE_RATE_PRECISION_E27
from src.modules.accounting.types import SECONDS_IN_YEAR, Shares


def calculate_gross_core_apr(
    post_internal_ether: int,
    post_internal_shares: Shares,
    shares_minted_as_fees: int,
    pre_total_ether: int,
    pre_total_shares: Shares,
    time_elapsed_seconds: int,
) -> Decimal:
    """
    Compute user-facing APR using share rate growth over time.
    https://docs.lido.fi/integrations/api/#last-lido-apr-for-steth

    // Emits when token rebased (total supply and/or total shares were changed)
    event TokenRebased(
        uint256 indexed reportTimestamp,
        uint256 timeElapsed,
        uint256 preTotalShares,
        uint256 preTotalEther, /* preTotalPooledEther */
        uint256 postTotalShares,
        uint256 postTotalEther, /* postTotalPooledEther */
        uint256 sharesMintedAsFees /* fee part included in `postTotalShares` */
    );

    preShareRate = preTotalEther * 1e27 / preTotalShares
    postShareRate = postTotalEther * 1e27 / postTotalShares

    userAPR =
        secondsInYear * (
            (postShareRate - preShareRate) / preShareRate
        ) / timeElapsed
    """
    if pre_total_shares == 0:
        raise ValueError("Cannot compute APR(pre_total_shares == 0): zero division risk.")

    if time_elapsed_seconds == 0:
        raise ValueError("Cannot compute APR. time_elapsed is 0")

    if post_internal_shares == shares_minted_as_fees:
        raise ValueError("Cannot compute APR(post_internal_shares == shares_minted_as_fees): zero division risk. ")

    shares_no_fees = post_internal_shares - shares_minted_as_fees

    post_share_rate_no_fees = Decimal(post_internal_ether * SHARE_RATE_PRECISION_E27) / Decimal(shares_no_fees)
    pre_share_rate = Decimal(pre_total_ether * SHARE_RATE_PRECISION_E27) / Decimal(pre_total_shares)

    rate_diff: Decimal = post_share_rate_no_fees - pre_share_rate

    if rate_diff < 0:
        return Decimal(0)

    return Decimal(SECONDS_IN_YEAR) * (rate_diff / pre_share_rate) / Decimal(time_elapsed_seconds)


def get_steth_by_shares(shares: int, total_ether: int, total_shares: int) -> Decimal:
    return (Decimal(shares) * Decimal(total_ether)) / Decimal(total_shares)
