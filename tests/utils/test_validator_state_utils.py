import pytest

from src.constants import (
    EFFECTIVE_BALANCE_INCREMENT,
    FAR_FUTURE_EPOCH,
    MAX_EFFECTIVE_BALANCE_ELECTRA,
    MIN_ACTIVATION_BALANCE,
)
from src.providers.consensus.types import Validator, ValidatorState
from src.types import EpochNumber, Gwei
from src.utils.validator_state import (
    calculate_active_effective_balance_sum,
    calculate_total_active_effective_balance,
    compute_activation_exit_epoch,
    get_activation_exit_churn_limit,
    get_balance_churn_limit,
    get_max_effective_balance,
    has_compounding_withdrawal_credential,
    has_eth1_withdrawal_credential,
    has_execution_withdrawal_credential,
    has_far_future_activation_eligibility_epoch,
    is_active_validator,
    is_exited_validator,
    is_fully_withdrawable_validator,
    is_on_exit,
    is_partially_withdrawable_validator,
)
from tests.factory.no_registry import ValidatorFactory
from tests.modules.accounting.bunker.test_bunker_abnormal_cl_rebase import (
    simple_validators,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("validators", "expected_balance"),
    [
        ([], 0),
        (
            [
                Validator(
                    '0',
                    '1',
                    ValidatorState('0x0', '', str(32 * 10**9), False, FAR_FUTURE_EPOCH, 15000, 15001, FAR_FUTURE_EPOCH),
                ),
                Validator(
                    '1',
                    '1',
                    ValidatorState(
                        '0x1', '', str(31 * 10**9), False, FAR_FUTURE_EPOCH, '14999', '15000', FAR_FUTURE_EPOCH
                    ),
                ),
                Validator(
                    '2',
                    '1',
                    ValidatorState(
                        '0x2', '', str(31 * 10**9), True, FAR_FUTURE_EPOCH, '15000', '15001', FAR_FUTURE_EPOCH
                    ),
                ),
            ],
            63 * 10**9,
        ),
        (
            [
                Validator(
                    '0',
                    '1',
                    ValidatorState(
                        '0x0', '', str(32 * 10**9), False, FAR_FUTURE_EPOCH, '14000', '14999', FAR_FUTURE_EPOCH
                    ),
                ),
                Validator(
                    '1',
                    '1',
                    ValidatorState(
                        '0x1', '', str(32 * 10**9), True, FAR_FUTURE_EPOCH, '15000', '15000', FAR_FUTURE_EPOCH
                    ),
                ),
            ],
            0,
        ),
    ],
)
def test_calculate_active_effective_balance_sum(validators, expected_balance):
    total_effective_balance = calculate_active_effective_balance_sum(validators, EpochNumber(15000))
    assert total_effective_balance == expected_balance


@pytest.mark.unit
@pytest.mark.parametrize(
    "activation_epoch, epoch, exit_epoch, expected",
    [
        (176720, 176720, 176722, True),
        (176720, 176721, 176722, True),
        (176900, 176900, 2**64 - 1, True),
        (176901, 176900, 2**64 - 1, False),
        (176720, 176720, 176720, False),
        (176900, 176720, 176720, False),
        (176900, 176720, 176750, False),
    ],
)
def test_is_active_validator(activation_epoch, epoch, exit_epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.activation_epoch = activation_epoch
    validator.validator.exit_epoch = exit_epoch

    actual = is_active_validator(validator, EpochNumber(epoch))
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "exit_epoch, epoch, expected",
    [
        (176720, 176722, True),
        (176730, 176722, False),
        (2**64 - 1, 176722, False),
    ],
)
def test_is_exited_validator(exit_epoch, epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.exit_epoch = exit_epoch

    actual = is_exited_validator(validator, EpochNumber(epoch))
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "exit_epoch, expected",
    [
        (176720, True),
        (FAR_FUTURE_EPOCH, False),
    ],
)
def test_is_on_exit(exit_epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.exit_epoch = exit_epoch

    actual = is_on_exit(validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "activation_eligibility_epoch, expected",
    [
        (176720, False),
        (FAR_FUTURE_EPOCH, True),
    ],
)
def test_has_far_future_activation_eligibility_epoch(activation_eligibility_epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.activation_eligibility_epoch = activation_eligibility_epoch

    actual = has_far_future_activation_eligibility_epoch(validator.validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "withdrawal_credentials, expected",
    [
        ('0x02ba', True),
        ('02ab', False),
        ('0x00ba', False),
        ('00ba', False),
    ],
)
def test_has_compounding_withdrawal_credential(withdrawal_credentials, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawal_credentials = withdrawal_credentials

    actual = has_compounding_withdrawal_credential(validator.validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "withdrawal_credentials, expected",
    [
        ('0x01ba', True),
        ('01ab', False),
        ('0x00ba', False),
        ('00ba', False),
    ],
)
def test_has_eth1_withdrawal_credential(withdrawal_credentials, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawal_credentials = withdrawal_credentials

    actual = has_eth1_withdrawal_credential(validator.validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "wc, expected",
    [
        ('0x01ba', True),
        ('01ab', False),
        ('0x00ba', False),
        ('00ba', False),
        ('0x02ba', True),
        ('02ab', False),
        ('0x00ba', False),
        ('00ba', False),
    ],
)
def test_has_execution_withdrawal_credential(wc, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawal_credentials = wc

    actual = has_execution_withdrawal_credential(validator.validator)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "withdrawable_epoch, wc, balance, epoch, expected",
    [
        (176720, '0x01ba', 32 * (10**10), 176722, True),
        (176722, '0x01ba', 32 * (10**10), 176722, True),
        (176723, '0x01ba', 32 * (10**10), 176722, False),
        (176722, '0x01ba', 0, 176722, False),
        (176720, '0x02ba', 32 * (10**10), 176722, True),
        (176722, '0x02ba', 32 * (10**10), 176722, True),
        (176723, '0x02ba', 32 * (10**10), 176722, False),
        (176722, '0x02ba', 0, 176722, False),
    ],
)
def test_is_fully_withdrawable_validator(withdrawable_epoch, wc, balance, epoch, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawable_epoch = withdrawable_epoch
    validator.validator.withdrawal_credentials = wc
    validator.balance = balance

    actual = is_fully_withdrawable_validator(validator.validator, validator.balance, EpochNumber(epoch))
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "effective_balance, add_balance, withdrawal_credentials, expected",
    [
        (32 * 10**9, 1, '0x01ba', True),
        (MAX_EFFECTIVE_BALANCE_ELECTRA, 1, '0x02ba', True),
        (32 * 10**9, 1, '0x0', False),
        (32 * 10**8, 0, '0x01ba', False),
        (MAX_EFFECTIVE_BALANCE_ELECTRA, 0, '0x02ba', False),
        (32 * 10**9, 0, '0x', False),
        (0, 0, '0x01ba', False),
        (0, 0, '0x02ba', False),
    ],
)
def test_is_partially_withdrawable(effective_balance, add_balance, withdrawal_credentials, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawal_credentials = withdrawal_credentials
    validator.validator.effective_balance = effective_balance
    validator.balance = effective_balance + add_balance

    actual = is_partially_withdrawable_validator(validator.validator, validator.balance)
    assert actual == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "wc, expected",
    [
        ('0x01ba', MIN_ACTIVATION_BALANCE),
        ('0x02ba', MAX_EFFECTIVE_BALANCE_ELECTRA),
        ('0x0', MIN_ACTIVATION_BALANCE),
    ],
)
def test_max_effective_balance(wc, expected):
    validator = ValidatorFactory.build()
    validator.validator.withdrawal_credentials = wc
    result = get_max_effective_balance(validator.validator)
    assert result == expected


class TestCalculateTotalEffectiveBalance:
    @pytest.fixture
    def validators(self):
        validators = ValidatorFactory.batch(2)

        validators[0].validator.activation_epoch = 170000
        validators[0].validator.exit_epoch = 2**64 - 1
        validators[0].validator.effective_balance = 1000000000
        validators[0].validator.withdrawal_credentials = '0x01ba'

        validators[1].validator.activation_epoch = 170001
        validators[1].validator.exit_epoch = 2**64 - 1
        validators[1].validator.effective_balance = 2000000000
        validators[1].validator.withdrawal_credentials = '0x01ba'

        return validators

    @pytest.mark.unit
    def test_no_validators(self):
        actual = calculate_total_active_effective_balance([], EpochNumber(170256))
        assert actual == Gwei(1 * 10**9)

    @pytest.mark.unit
    def test_all_active(self, validators: list[Validator]):
        actual = calculate_total_active_effective_balance(validators, EpochNumber(170256))
        assert actual == Gwei(3000000000)

    @pytest.mark.unit
    def test_no_balance_validators(self):
        actual = calculate_total_active_effective_balance(
            simple_validators(0, 9, effective_balance="0"), EpochNumber(170256)
        )
        assert actual == EFFECTIVE_BALANCE_INCREMENT

    @pytest.mark.unit
    def test_skip_exiting(self, validators: list[Validator]):
        validators[0].validator.exit_epoch = EpochNumber(170256)

        actual = calculate_total_active_effective_balance(validators, EpochNumber(170256))
        assert actual == Gwei(2000000000)

    @pytest.mark.unit
    def test_skip_exited(self, validators: list[Validator]):
        validators[0].validator.exit_epoch = EpochNumber(170000)

        actual = calculate_total_active_effective_balance(validators, EpochNumber(170256))
        assert actual == Gwei(2000000000)

    @pytest.mark.unit
    def test_skip_exited_slashed(self, validators: list[Validator]):
        validators[0].validator.exit_epoch = EpochNumber(170256)
        validators[0].validator.slashed = True

        actual = calculate_total_active_effective_balance(validators, EpochNumber(170256))
        assert actual == Gwei(2000000000)

    @pytest.mark.unit
    def test_include_slashed(self, validators: list[Validator]):
        validators[0].validator.slashed = True

        actual = calculate_total_active_effective_balance(validators, EpochNumber(170256))
        assert actual == Gwei(3000000000)

    @pytest.mark.unit
    def test_skip_ongoing(self, validators: list[Validator]):
        validators[0].validator.activation_epoch = EpochNumber(170257)

        actual = calculate_total_active_effective_balance(validators, EpochNumber(170256))
        assert actual == Gwei(2000000000)


@pytest.mark.unit
def test_compute_activation_exit_epoch():
    ref_epoch = EpochNumber(3455)
    assert 3460 == compute_activation_exit_epoch(ref_epoch)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("total_active_balance", "expected_limit"),
    (
        (0, 128e9),
        (32e9, 128e9),
        (2 * 32e9, 128e9),
        (1024 * 32e9, 128e9),
        (512 * 1024 * 32e9, 256e9),
        (1024 * 1024 * 32e9, 512e9),
        (2000 * 1024 * 32e9, 1000e9),
        (3300 * 1024 * 32e9, 1650e9),
    ),
)
def test_get_balance_churn_limit(total_active_balance: Gwei, expected_limit: Gwei):
    actual_limit = get_balance_churn_limit(total_active_balance)
    assert actual_limit == expected_limit, "Unexpected balance churn limit"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("total_active_balance", "expected_limit"),
    (
        (0, 128e9),
        (32e9, 128e9),
        (2 * 32e9, 128e9),
        (1024 * 32e9, 128e9),
        (512 * 1024 * 32e9, 256e9),
        (1024 * 1024 * 32e9, 256e9),
        (2000 * 1024 * 32e9, 256e9),
        (3300 * 1024 * 32e9, 256e9),
    ),
)
def test_compute_exit_balance_churn_limit(total_active_balance: Gwei, expected_limit: Gwei):
    actual_limit = get_activation_exit_churn_limit(total_active_balance)
    assert actual_limit == expected_limit, "Unexpected exit churn limit"
