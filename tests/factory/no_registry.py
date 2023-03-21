import random
from itertools import count

from faker import Faker
from pydantic_factories import Use

from src.providers.consensus.typings import Validator, ValidatorState
from src.providers.keys.typings import LidoKey
from tests.factory.web3_factory import Web3Factory
from src.web3py.extensions.lido_validators import StakingModule, LidoValidator, NodeOperator


faker = Faker()


class ValidatorStateFactory(Web3Factory):
    __model__ = ValidatorState


class ValidatorFactory(Web3Factory):
    __model__ = Validator


class LidoKeyFactory(Web3Factory):
    __model__ = LidoKey

    @classmethod
    def generate_for_validators(cls, validators: list[Validator], **kwargs):
        return cls.butch_with('key', [v.validator.pubkey for v in validators], **kwargs)


class StakingModuleFactory(Web3Factory):
    __model__ = StakingModule

    id: int = Use(lambda x: next(x), count(1))
    name: str = faker.name


class LidoValidatorFactory(Web3Factory):
    __model__ = LidoValidator

    balance: str = Use(lambda x: str(x), random.randrange(1, 10**9))


class NodeOperatorFactory(Web3Factory):
    __model__ = NodeOperator

    id: int = Use(lambda x: next(x), count(1))
