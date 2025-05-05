from typing import Any, Iterable

from src.providers.consensus.types import Validator, BeaconStateView, BlockHeaderFullResponse
from tests.factory.web3_factory import Web3DataclassFactory


class BeaconStateViewFactory(Web3DataclassFactory[BeaconStateView]):
    @classmethod
    def build_with_validators(cls, validators: Iterable[Validator], **kwargs: Any):
        return cls.build(
            validators=[v.validator for v in validators],
            balances=[v.balance for v in validators],
            **kwargs,
        )


class BlockHeaderFullResponseFactory(Web3DataclassFactory[BlockHeaderFullResponse]):
    finalized: bool = True

    @classmethod
    def build(cls, **kwargs) -> BlockHeaderFullResponse:
        instance = super().build(**kwargs)
        instance.data.canonical = True
        return instance
