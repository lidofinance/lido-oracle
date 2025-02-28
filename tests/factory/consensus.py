from typing import Any, Iterable

from src.providers.consensus.types import BeaconStateView, Validator
from tests.factory.web3_factory import Web3Factory


class BeaconStateViewFactory(Web3Factory):
    __model__ = BeaconStateView

    @classmethod
    def build_with_validators(cls, validators: Iterable[Validator], **kwargs: Any):
        return cls.build(
            validators=[v.validator for v in validators],
            balances=[v.balance for v in validators],
            **kwargs,
        )
