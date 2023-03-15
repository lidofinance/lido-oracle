import pytest

from src.utils.validator_state import *
from tests.factory.no_registry import ValidatorFactory
from tests.modules.accounting.bunker.test_bunker_medterm_penalty import simple_validators
from typings import EpochNumber


@pytest.mark.unit
@pytest.mark.parametrize("activation_epoch, epoch, exit_epoch, expected", [
    (176720, 176720, 176722, True),
    (176720, 176721, 176722, True),
    (176900, 176900, 2 ** 64 - 1, True),
    (176901, 176900, 2 ** 64 - 1, False),
    (176720, 176720, 176720, False),
    (176900, 176720, 176720, False),
    (176900, 176720, 176750, False),
])
def test_is_active_validator(activation_epoch, epoch, exit_epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.activation_epoch = activation_epoch
    validator.validator.exit_epoch = exit_epoch

    actual = is_active_validator(validator, EpochNumber(epoch))
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize("exit_epoch, epoch, expected", [
    (176720, 176722, True),
    (176730, 176722, False),
    (2 ** 64 - 1, 176722, False),
])
def test_is_exited_validator(exit_epoch, epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.exit_epoch = exit_epoch

    actual = is_exited_validator(validator, EpochNumber(epoch))
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize("exit_epoch, expected", [
    (176720, True),
    (2 ** 64 - 1, False),
])
def test_is_on_exit(exit_epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.exit_epoch = exit_epoch

    actual = is_on_exit(validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize("withdrawal_credentials, expected", [
    ('0x01ba', True),
    ('01ab', False),
    ('0x00ba', False),
    ('00ba', False),
])
def test_has_eth1_withdrawal_credential(withdrawal_credentials, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawal_credentials = withdrawal_credentials

    actual = has_eth1_withdrawal_credential(validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize("withdrawable_epoch, balance, epoch, expected", [
    (176720, 32 * (10 ** 10), 176722, True),
    (176722, 32 * (10 ** 10), 176722, True),
    (176723, 32 * (10 ** 10), 176722, False),
    (176722, 0, 176722, False),
])
def test_is_fully_withdrawable_validator(withdrawable_epoch, balance, epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawable_epoch = withdrawable_epoch
    validator.validator.withdrawal_credentials = '0x01ba'
    validator.balance = balance

    actual = is_fully_withdrawable_validator(validator, EpochNumber(epoch))
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize("activation_epoch, exit_epoch, epoch, expected", [
    (170000, 2 ** 64 - 1, 170256, True),
    (170000, 170200, 170256, False),
    (170000, 2 ** 64 - 1, 170255, False),
])
def test_is_validator_eligible_to_exit(activation_epoch, exit_epoch, epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.activation_epoch = activation_epoch
    validator.validator.exit_epoch = exit_epoch

    actual = is_validator_eligible_to_exit(validator, EpochNumber(epoch))
    assert actual == expected


def get_validators():
    validators = ValidatorFactory.batch(2)

    validators[0].validator.activation_epoch = 170000
    validators[0].validator.exit_epoch = 2 ** 64 - 1
    validators[0].validator.effective_balance = 1000000000
    validators[0].validator.withdrawal_credentials = '0x01ba'

    validators[1].validator.activation_epoch = 170001
    validators[1].validator.exit_epoch = 2 ** 64 - 1
    validators[1].validator.effective_balance = 2000000000
    validators[1].validator.withdrawal_credentials = '0x01ba'

    return validators


@pytest.mark.unit
def test_is_validator_eligible_to_exit():
    actual = calculate_total_active_effective_balance(get_validators(), EpochNumber(170256))
    assert actual == Gwei(3000000000)

    actual = calculate_total_active_effective_balance(simple_validators(0, 9, effective_balance=0), EpochNumber(170256))
    assert actual == EFFECTIVE_BALANCE_INCREMENT

    vals = get_validators()
    vals[0].validator.exit_epoch = 170000  # non active validator

    actual = calculate_total_active_effective_balance(vals, EpochNumber(170256))
    assert actual == Gwei(2000000000)
