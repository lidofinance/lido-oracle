import random
from itertools import count
from typing import Any

from faker import Faker
from hexbytes import HexBytes
from polyfactory import Use

from src.constants import (
    COMPOUNDING_WITHDRAWAL_PREFIX,
    EFFECTIVE_BALANCE_INCREMENT,
    ETH1_ADDRESS_WITHDRAWAL_PREFIX,
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE,
)
from src.providers.consensus.types import Validator, ValidatorState
from src.providers.keys.types import LidoKey
from src.types import Gwei, NodeOperatorId, StakingModuleId
from src.web3py.extensions.lido_validators import LidoValidator, NodeOperator, StakingModule
from tests.factory.web3_factory import Web3DataclassFactory


faker = Faker()


class ValidatorStateFactory(Web3DataclassFactory[ValidatorState]):
    __set_as_default_factory_for_type__ = True
    withdrawal_credentials = "0x01"
    exit_epoch = FAR_FUTURE_EPOCH

    @classmethod
    def build(cls, **kwargs: Any):
        kwargs.setdefault('pubkey', HexBytes(faker.binary(48)).hex())
        return super().build(**kwargs)


class ValidatorFactory(Web3DataclassFactory[Validator]):  # noqa: E701
    ...


class LidoKeyFactory(Web3DataclassFactory[LidoKey]):
    used: bool = True

    @classmethod
    def generate_for_validators(cls, validators: list[Validator], **kwargs):
        return [cls.build(key=v.validator.pubkey, **kwargs) for v in validators]


class StakingModuleFactory(Web3DataclassFactory[StakingModule]):
    id: StakingModuleId = Use(lambda x: StakingModuleId(next(x)), count(1))
    name: str = faker.name


class LidoValidatorFactory(Web3DataclassFactory[LidoValidator]):
    index: int = Use(lambda x: next(x), count(1))
    balance: Gwei = Use(lambda x: Gwei(x), random.randrange(1, 10**9))

    @classmethod
    def build(cls, **kwargs: Any) -> "LidoValidator":
        kwargs.setdefault("consolidating_as_source_initialized", True)
        kwargs.setdefault("pending_topups", [])
        kwargs.setdefault("consolidating_as_target", [])
        obj = super().build(**kwargs)
        # polyfactory may discard unknown kwargs — ensure init flags are set
        obj._consolidation_as_source_initialized = True
        if obj._pending_topups is None:
            obj._pending_topups = []
        if obj._consolidating_as_target is None:
            obj._consolidating_as_target = []
        return obj

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


class NodeOperatorFactory(Web3DataclassFactory[NodeOperator]):
    id: NodeOperatorId = Use(lambda x: NodeOperatorId(next(x)), count(1))
