import random
from itertools import count
from typing import Any

from faker import Faker
from pydantic_factories import Use

from src.constants import FAR_FUTURE_EPOCH
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.keys.types import LidoKey
from tests.factory.web3_factory import Web3Factory
from src.web3py.extensions.lido_validators import StakingModule, LidoValidator, NodeOperator

faker = Faker()


class ValidatorStateFactory(Web3Factory):
    __model__ = ValidatorState

    exit_epoch = FAR_FUTURE_EPOCH


class ValidatorFactory(Web3Factory):
    __model__ = Validator


class LidoKeyFactory(Web3Factory):
    __model__ = LidoKey

    used: bool = True

    @classmethod
    def generate_for_validators(cls, validators: list[Validator], **kwargs):
        return cls.batch_with('key', [v.validator.pubkey for v in validators], **kwargs)


class StakingModuleFactory(Web3Factory):
    __model__ = StakingModule

    id: int = Use(lambda x: next(x), count(1))
    name: str = faker.name


class LidoValidatorFactory(Web3Factory):
    __model__ = LidoValidator

    index: str = Use(lambda x: str(next(x)), count(1))
    balance: str = Use(lambda x: str(x), random.randrange(1, 10**9))

    @classmethod
    def build_with_activation_epoch_bound(cls, max_value: int, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(activation_epoch=str(faker.pyint(max_value=max_value - 1))), **kwargs
        )


class NodeOperatorFactory(Web3Factory):
    __model__ = NodeOperator

    id: int = Use(lambda x: next(x), count(1))
