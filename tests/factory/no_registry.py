import random
from itertools import count
from typing import Any

from faker import Faker
from hexbytes import HexBytes
from pydantic_factories import Use

from src.constants import (
    COMPOUNDING_WITHDRAWAL_PREFIX,
    EFFECTIVE_BALANCE_INCREMENT,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
    MIN_ACTIVATION_BALANCE,
    GWEI_TO_WEI,
)
from src.providers.consensus.types import PendingDeposit, Validator, ValidatorState
from src.providers.keys.types import LidoKey
from src.types import Gwei
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperator, StakingModule
from tests.factory.web3_factory import Web3Factory

faker = Faker()


class ValidatorStateFactory(Web3Factory):
    __model__ = ValidatorState

    withdrawal_credentials = "0x01"
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
            balance=0,
            validator=ValidatorStateFactory.build(
                activation_eligibility_epoch=FAR_FUTURE_EPOCH,
                activation_epoch=FAR_FUTURE_EPOCH,
                exit_epoch=FAR_FUTURE_EPOCH,
                effective_balance=0,
            ),
            **kwargs,
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

    index: str = Use(lambda x: next(x), count(1))
    balance: str = Use(lambda x: x, random.randrange(1, 10**9))

    @classmethod
    def build_with_activation_epoch_bound(cls, max_value: int, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=faker.pyint(max_value=max_value - 1), effective_balance=Gwei(32 * 10**9)
            ),
            **kwargs,
        )

    @classmethod
    def build_transition_period_pending_deposit_vals(cls, **kwargs: Any):
        return cls.build(
            balance=str(0),
            validator=ValidatorStateFactory.build(
                activation_eligibility_epoch=FAR_FUTURE_EPOCH,
                activation_epoch=FAR_FUTURE_EPOCH,
                exit_epoch=FAR_FUTURE_EPOCH,
                effective_balance=0,
            ),
            **kwargs,
        )

    @classmethod
    def build_not_active_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=faker.pyint(min_value=epoch + 1, max_value=FAR_FUTURE_EPOCH),
                exit_epoch=FAR_FUTURE_EPOCH,
            ),
            **kwargs,
        )

    @classmethod
    def build_active_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=faker.pyint(min_value=0, max_value=epoch - 1),
                exit_epoch=faker.pyint(min_value=epoch + 1, max_value=FAR_FUTURE_EPOCH),
            ),
            **kwargs,
        )

    @classmethod
    def build_exit_vals(cls, epoch, **kwargs: Any):
        return cls.build(
            validator=ValidatorStateFactory.build(
                activation_epoch=0,
                exit_epoch=faker.pyint(min_value=1, max_value=epoch),
            ),
            **kwargs,
        )

    @classmethod
    def build_with_balance(cls, balance: float, meb: int = MAX_EFFECTIVE_BALANCE, **kwargs: Any):
        return cls.build(
            balance=balance,
            validator=ValidatorStateFactory.build(
                effective_balance=min(balance - balance % EFFECTIVE_BALANCE_INCREMENT, meb),
                withdrawal_credentials=(
                    ETH1_ADDRESS_WITHDRAWAL_PREFIX if meb == MAX_EFFECTIVE_BALANCE else COMPOUNDING_WITHDRAWAL_PREFIX
                ),
            ),
            **kwargs,
        )


class PendingDepositFactory(Web3Factory):
    __model__ = PendingDeposit

    @classmethod
    def generate_for_validators(cls, validators: list[Validator], **kwargs):
        return cls.batch_with('pubkey', [v.validator.pubkey for v in validators], **kwargs)


class NodeOperatorFactory(Web3Factory):
    __model__ = NodeOperator

    id: int = Use(lambda x: next(x), count(1))
