from src.providers.consensus.client import ConsensusClient


class ValidatorsExit:
    def __init__(self, validators, max_size: int):

        self._current_index = 0

    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration
