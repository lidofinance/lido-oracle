import random
from itertools import count
from typing import Any

from faker import Faker
from pydantic_factories import Use

from src.constants import EFFECTIVE_BALANCE_INCREMENT, FAR_FUTURE_EPOCH, MAX_EFFECTIVE_BALANCE, MIN_ACTIVATION_BALANCE
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.keys.types import LidoKey
from src.types import Gwei
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperator, StakingModule
from tests.factory.web3_factory import Web3Factory

faker = Faker()


class ValidatorStateFactory(Web3Factory):
    __model__ = ValidatorState

    withdrawal_credentials = "0x01"
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

    @classmethod
    def build_not_active_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=str(faker.pyint(min_value=epoch + 1, max_value=FAR_FUTURE_EPOCH)),
                exit_epoch=str(FAR_FUTURE_EPOCH),
            ),
            **kwargs,
        )

    @classmethod
    def build_active_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=str(faker.pyint(min_value=0, max_value=epoch - 1)),
                exit_epoch=str(faker.pyint(min_value=epoch + 1, max_value=FAR_FUTURE_EPOCH)),
            ),
            **kwargs,
        )

    @classmethod
    def build_exit_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch='0',
                exit_epoch=str(faker.pyint(min_value=1, max_value=epoch)),
            ),
            **kwargs,
        )

    @classmethod
    def build_with_balance(cls, balance: float, meb: int = MAX_EFFECTIVE_BALANCE, **kwargs: Any):
        return cls.build(
            balance=balance,
            validator=ValidatorStateFactory.build(
                effective_balance=min(balance - balance % EFFECTIVE_BALANCE_INCREMENT, meb),
                withdrawal_credentials="0x01" if meb == MAX_EFFECTIVE_BALANCE else "0x02",
            ),
            **kwargs,
        )


class NodeOperatorFactory(Web3Factory):
    __model__ = NodeOperator

    id: int = Use(lambda x: next(x), count(1))
