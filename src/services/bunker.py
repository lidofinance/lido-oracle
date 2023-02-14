from src.web3py.typings import Web3


class BunkerService:
    def __init__(self, w3: Web3):
        self.w3 = w3

    def is_bunker_mode(self) -> bool:
        pass

    def _check_slashings(self):
        pass

    def _check_activity_leak(self):
        pass
