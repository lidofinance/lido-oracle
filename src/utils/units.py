"""A set of utils to convert ether units"""

from web3.types import Wei

from src.constants import GWEI_TO_WEI
from src.types import Gwei


def wei_to_gwei(amount: Wei) -> Gwei:
    """Converts Wei to Gwei rounding down"""
    return Gwei(amount // GWEI_TO_WEI)


def gwei_to_wei(amount: Gwei) -> Wei:
    """Converts Gwei to Wei"""
    return Wei(amount * GWEI_TO_WEI)
