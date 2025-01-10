import random
from itertools import count
from typing import Any

from faker import Faker
from hexbytes import HexBytes
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

    @classmethod
    def build(cls, **kwargs: Any):
        if 'pubkey' not in kwargs:
            kwargs['pubkey'] = HexBytes(faker.binary(length=48)).hex()
        return super().build(**kwargs)


class ValidatorFactory(Web3Factory):
    __model__ = Validator

    @classmethod
    def build_pending_deposit_vals(cls, **kwargs: Any):
        return cls.build(
            balance=str(0),
            validator=ValidatorStateFactory.build(
                activation_eligibility_epoch=str(FAR_FUTURE_EPOCH),
                activation_epoch=str(FAR_FUTURE_EPOCH),
                exit_epoch=str(FAR_FUTURE_EPOCH),
                effective_balance=str(0),
            ),
            **kwargs
        )


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
    def build_pending_deposit_vals(cls, **kwargs: Any):
        return cls.build(
            balance=str(0),
            validator=ValidatorStateFactory.build(
                activation_eligibility_epoch=str(FAR_FUTURE_EPOCH),
                activation_epoch=str(FAR_FUTURE_EPOCH),
                exit_epoch=str(FAR_FUTURE_EPOCH),
                effective_balance=str(0),
            ),
            **kwargs
        )

    @classmethod
    def build_not_active_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=str(faker.pyint(min_value=epoch + 1, max_value=FAR_FUTURE_EPOCH)),
                exit_epoch=str(FAR_FUTURE_EPOCH),
            ),
            **kwargs
        )

    @classmethod
    def build_active_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=str(faker.pyint(min_value=0, max_value=epoch - 1)),
                exit_epoch=str(faker.pyint(min_value=epoch + 1, max_value=FAR_FUTURE_EPOCH)),
            ),
            **kwargs
        )

    @classmethod
    def build_exit_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch='0',
                exit_epoch=str(faker.pyint(min_value=1, max_value=epoch)),
            ),
            **kwargs
        )


class NodeOperatorFactory(Web3Factory):
    __model__ = NodeOperator

    id: int = Use(lambda x: next(x), count(1))
