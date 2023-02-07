from web3 import Web3
from web3.types import Wei

from src.typings import BlockStamp


class PredictionModule:
    def __init__(self, w3: Web3):
        self._w3 = w3

    def get_prediction_rewards_per_epoch(self, blockstamp: BlockStamp, reports_amount: int) -> Wei:
        """
        1. Read previous N report events.
        2. Get median income
        3. return median income / epoch_per_day
        """
        pass
