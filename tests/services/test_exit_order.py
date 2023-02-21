import pytest

from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import ValidatorState, Validator
from src.providers.keys.typings import LidoKey
from src.services.exit_order import ValidatorsExit, NodeOperatorPredictableState
from src.typings import BlockStamp
from src.web3py.extentions.lido_validators import LidoValidator, StakingModuleId, NodeOperatorId, NodeOperator, \
    StakingModule

FAR_FUTURE_EPOCH = 2 ** 64 - 1


@pytest.fixture()
def past_blockstamp():
    yield BlockStamp(
        block_root='0x85c753bd0674f483dceeb138e7b35554291176a3edb6274c57b0bbd158dca050',
        state_root='0x4a5424e368d5b4c2f971f76fd4435f289c2966330a65caac292e4ed73ec007b1',
        slot_number=142271,
        block_hash='0xf95212b31c976ad09af3af4e627859eaa425b2513c939112074cf14bc04e21d0',
        block_number=135080,
        block_timestamp=1676970852,
        ref_slot=142271,
        ref_epoch=4445
    )


@pytest.fixture(
    params=[
        # module, operator ids, returned indexes
        {
            (0, (0, 1)): [-1, 100500],
            (1, (1,)): [-1],
        },
    ],
    ids=['last_requested_validator_indices_default']
)
def last_requested_validator_indices_mocks_map(request):
    return request.param


@pytest.fixture(
    params=[
        # from_bloc, to_block, returned events
        {(3, 13): [
            {'args': (0, 0, 2, '', 48)},
            {'args': (0, 0, 3, '', 60)},
            {'args': (0, 0, 4, '', 84)},
            {'args': (0, 0, 5, '', 120)},
            {'args': (0, 0, 6, '', 144)},
            {'args': (0, 1, 7, '', 168)},
            {'args': (1, 1, 8, '', 216)},
            {'args': (0, 0, 10, '', 276)}
        ]}
    ],
    ids=['validator_exit_request_events_default']
)
def validator_exit_request_mock(request):
    return request.param


@pytest.fixture
def validator_exit(
    web3,
    contracts,
    lido_validators,
    past_blockstamp,
    last_requested_validator_indices_mocks_map,
    validator_exit_request_mock,
) -> ValidatorsExit:
    """Returns minimal initialized ValidatorsExit service instance with mocked methods"""
    service = object.__new__(ValidatorsExit)
    service.w3 = web3
    service.blockstamp = past_blockstamp
    service.c_conf = ChainConfig(32, 12, 0)
    service.validator_delayed_timeout_in_slots = 3600
    service.left_queue_count = 0
    service.validator_delayed_timeout_in_slots = 10

    def mock_last_requested_validator_indices(module, operator_indexes):
        _func = lambda _: _
        _func.call = lambda *args, **kwargs: last_requested_validator_indices_mocks_map[(module, tuple(operator_indexes))]
        return _func

    service.w3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices = (
        mock_last_requested_validator_indices
    )

    service.w3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest.get_logs = (
        lambda fromBlock, toBlock: (
            validator_exit_request_mock[(fromBlock, toBlock)]
        )
    )
    return service


# -- With mocks --


@pytest.mark.unit
def test_get_last_requested_validator_index(validator_exit, past_blockstamp):
    """Check that wrapper work as expected and return mocked values"""
    assert validator_exit._get_last_requested_validator_index(past_blockstamp, 0, [0, 1]) == [-1, 100500]


@pytest.mark.unit
def test_get_validator_exit_events(validator_exit):
    """Check that wrapper work as expected and return mocked values"""
    assert validator_exit._get_validator_exit_events(3, 13) == [
        {'args': (0, 0, 2, '', 48)},
        {'args': (0, 0, 3, '', 60)},
        {'args': (0, 0, 4, '', 84)},
        {'args': (0, 0, 5, '', 120)},
        {'args': (0, 0, 6, '', 144)},
        {'args': (0, 1, 7, '', 168)},
        {'args': (1, 1, 8, '', 216)},
        {'args': (0, 0, 10, '', 276)}
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    'blockstamp, operator_indexes, expected_value',
    [
        (
            BlockStamp('', '', 18, '', 13, 0, 22, 0),
            [(0, 0), (0, 1), (1, 1)],
            {(0, 0): {10}, (0, 1): {7}, (1, 1): {8}}
        )
    ],
)
def test_get_recently_requested_to_exit_indices(
    validator_exit, blockstamp, operator_indexes, expected_value
):
    result = validator_exit._get_recently_requested_to_exit_indices(blockstamp, operator_indexes)
    assert result == expected_value


@pytest.mark.unit
@pytest.mark.parametrize(
    'blockstamp, operator_indexes, expected_value',
    [
        (
            BlockStamp('', '', 18, '', 13, 0, 22, 0),
            [(0, 0), (0, 1), (1, 1)],
            {(0, 0): -1, (0, 1): 100500, (1, 1): -1}
        )
    ],
)
def test_get_last_requested_to_exit_indices(
    validator_exit, blockstamp, operator_indexes, expected_value
):
    result = validator_exit._get_last_requested_to_exit_indices(blockstamp, operator_indexes)
    assert result == expected_value


@pytest.mark.unit
def test_prepare_lido_node_operator_stats(validator_exit):

    def v(module_address, operator, index, activation_epoch, exit_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.key = object.__new__(LidoKey)
        validator.validator = object.__new__(Validator)
        validator.validator.validator = object.__new__(ValidatorState)
        validator.key.moduleAddress = module_address
        validator.key.operatorIndex = operator
        validator.validator.index = index
        validator.validator.validator.activation_epoch = activation_epoch
        validator.validator.validator.exit_epoch = exit_epoch
        return validator

    def n(
        index,
        is_limited,
        target_count,
        refunded_count,
        total_deposited,
        module_id,
        module_address
    ):
        operator = object.__new__(NodeOperator)
        operator.staking_module = object.__new__(StakingModule)
        operator.id = index
        operator.is_target_limit_active = is_limited
        operator.target_validators_count = target_count
        operator.refunded_validators_count = refunded_count
        operator.total_deposited_validators = total_deposited
        operator.staking_module.id = module_id
        operator.staking_module.staking_module_address = module_address
        return operator

    operators = [
        n(0, False, 2, 0, 2, 0, '0x0'),
        n(1, False, 2, 0, 2, 0, '0x0'),
        n(1, False, 2, 0, 2, 1, '0x1'),
    ]

    operator_validators = {
        (0, 0): [v('0x0', 0, 47, 500, FAR_FUTURE_EPOCH)],
        (0, 1): [v('0x0', 1, 90, 1500, FAR_FUTURE_EPOCH)],
        (1, 1): [v('0x1', 1, 50, 1000, 0)],
    }
    validator_exit.blockstamp = BlockStamp('', '', 18, '', 13, 0, 22, 0)
    result = validator_exit._prepare_lido_node_operator_stats(
        BlockStamp('', '', 18, '', 13, 0, 22, 0),
        operators,
        operator_validators,
    )

    expected_operator_predictable_states = {
        (0, 0): NodeOperatorPredictableState(
            predictable_validators_total_age=0,
            predictable_validators_count=2,
            targeted_validators=None,
            delayed_validators=0
        ),
        (0, 1): NodeOperatorPredictableState(
            predictable_validators_total_age=0,
            predictable_validators_count=1,
            targeted_validators=None,
            delayed_validators=1
        ),
        (1, 1): NodeOperatorPredictableState(
            predictable_validators_total_age=0,
            predictable_validators_count=1,
            targeted_validators=None,
            delayed_validators=0
        )
    }

    assert result == expected_operator_predictable_states


# -- Statics without mocks --


@pytest.mark.unit
def test_predicates():

    def v(module_address, operator, index, activation_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.key = object.__new__(LidoKey)
        validator.validator = object.__new__(Validator)
        validator.validator.validator = object.__new__(ValidatorState)
        validator.key.moduleAddress = module_address
        validator.key.operatorIndex = operator
        validator.validator.index = index
        validator.validator.validator.activation_epoch = activation_epoch
        return validator

    exitable_validators_random_sort = [
        v('0x1', 2, 76, 1200),
        v('0x4', 2, 1121, 3210),
        v('0x5', 1, 1122, 3210),
        v('0x2', 1, 81, 1400),
        v('0x2', 2, 48, 781),
        v('0x3', 1, 49, 990),
        v('0x4', 1, 10, 231),
        v('0x0', 2, 90, 1500),
        v('0x1', 1, 50, 1000),
        v('0x3', 2, 52, 1003),
        v('0x0', 1, 47, 500),
    ]

    validators_exit = object.__new__(ValidatorsExit)
    validators_exit.staking_module_id = {
        '0x0': StakingModuleId(0),
        '0x1': StakingModuleId(1),
        '0x2': StakingModuleId(2),
        '0x3': StakingModuleId(3),
        '0x4': StakingModuleId(4),
        '0x5': StakingModuleId(5),
    }
    validators_exit.total_predictable_validators_count = 500000

    validators_exit.lido_node_operator_stats = {
        (StakingModuleId(0), NodeOperatorId(1)): NodeOperatorPredictableState(1000, 7000, 10, 0),
        (StakingModuleId(0), NodeOperatorId(2)): NodeOperatorPredictableState(1000, 7000, 10, 0),
        (StakingModuleId(1), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(1), NodeOperatorId(2)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(2), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(2), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(3), NodeOperatorId(1)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(3), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(4), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 5, 50, 1),
        (StakingModuleId(4), NodeOperatorId(2)): NodeOperatorPredictableState(100500, 2, None, 2),
        (StakingModuleId(5), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 2, None, 2),
    }

    exitable_validators_random_sort.sort(key=lambda validator: ValidatorsExit._predicates(validators_exit, validator))
    exitable_validators_indexes = [v.validator.index for v in exitable_validators_random_sort]

    expected_queue_sort_indexes = [47, 90, 50, 76, 81, 48, 49, 52, 10, 1121, 1122]
    assert exitable_validators_indexes == expected_queue_sort_indexes


@pytest.mark.unit
def test_decrease_node_operator_stats(past_blockstamp):

    def v(module_address, operator, index, activation_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.key = object.__new__(LidoKey)
        validator.validator = object.__new__(Validator)
        validator.validator.validator = object.__new__(ValidatorState)
        validator.key.moduleAddress = module_address
        validator.key.operatorIndex = operator
        validator.validator.index = index
        validator.validator.validator.activation_epoch = activation_epoch
        return validator

    exitable_validators = [
        v('0x1', 2, 76, 1200),
        v('0x4', 2, 1121, 5000),
    ]

    validator_exit = object.__new__(ValidatorsExit)
    validator_exit.total_predictable_validators_count = 500000
    validator_exit.blockstamp = past_blockstamp
    validator_exit.staking_module_id = {
        '0x0': StakingModuleId(0),
        '0x1': StakingModuleId(1),
        '0x2': StakingModuleId(2),
        '0x3': StakingModuleId(3),
        '0x4': StakingModuleId(4),
        '0x5': StakingModuleId(5),
    }
    validator_exit.lido_node_operator_stats = {
        (StakingModuleId(0), NodeOperatorId(1)): NodeOperatorPredictableState(1000, 7000, 10, 0),
        (StakingModuleId(0), NodeOperatorId(2)): NodeOperatorPredictableState(1000, 7000, 10, 0),
        (StakingModuleId(1), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(1), NodeOperatorId(2)): NodeOperatorPredictableState(3245, 6000, 2, 0),
        (StakingModuleId(2), NodeOperatorId(1)): NodeOperatorPredictableState(1200, 6000, 2, 0),
        (StakingModuleId(2), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(3), NodeOperatorId(1)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(3), NodeOperatorId(2)): NodeOperatorPredictableState(998, 7432, None, 0),
        (StakingModuleId(4), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 5, 50, 1),
        (StakingModuleId(4), NodeOperatorId(2)): NodeOperatorPredictableState(100500, 2, None, 2),
        (StakingModuleId(5), NodeOperatorId(1)): NodeOperatorPredictableState(100500, 2, None, 2),
    }

    validator_exit._decrease_node_operator_stats(exitable_validators[0])
    expected_after_decrease_first = NodeOperatorPredictableState(0, 5999, 2, 0)
    assert validator_exit.total_predictable_validators_count == 499999
    assert (
        validator_exit.lido_node_operator_stats[(StakingModuleId(1), NodeOperatorId(2))] == expected_after_decrease_first
    )

    validator_exit._decrease_node_operator_stats(exitable_validators[1])
    expected_after_decrease_second = NodeOperatorPredictableState(100500, 1, None, 2)
    assert validator_exit.total_predictable_validators_count == 499998
    assert (
        validator_exit.lido_node_operator_stats[(StakingModuleId(4), NodeOperatorId(2))] == expected_after_decrease_second
    )



@pytest.mark.unit
def test_get_delayed_validators_per_operator():
    def v(index, exit_epoch) -> LidoValidator:
        validator = object.__new__(LidoValidator)
        validator.validator = object.__new__(Validator)
        validator.validator.validator = object.__new__(ValidatorState)
        validator.validator.index = index
        validator.validator.validator.exit_epoch = exit_epoch
        return validator

    last_requested_to_exit_indices_per_operator = {
        (StakingModuleId(0), NodeOperatorId(1)): -1,
        (StakingModuleId(0), NodeOperatorId(2)): -1,
        (StakingModuleId(1), NodeOperatorId(1)): -1,
        (StakingModuleId(1), NodeOperatorId(2)): -1,
        (StakingModuleId(2), NodeOperatorId(1)): 10000,
        (StakingModuleId(2), NodeOperatorId(2)): 10000,
        (StakingModuleId(3), NodeOperatorId(1)): 10000,
        (StakingModuleId(3), NodeOperatorId(2)): 10000,
    }
    operator_validators = {
        (StakingModuleId(0), NodeOperatorId(1)): [v(1, 100500), v(2, 100500)],
        (StakingModuleId(0), NodeOperatorId(2)): [v(3, 100500), v(4, 100500)],
        (StakingModuleId(1), NodeOperatorId(1)): [v(5, FAR_FUTURE_EPOCH), v(6, FAR_FUTURE_EPOCH)],
        (StakingModuleId(1), NodeOperatorId(2)): [v(7, FAR_FUTURE_EPOCH), v(8, FAR_FUTURE_EPOCH)],
        (StakingModuleId(2), NodeOperatorId(1)): [v(9, 100500), v(10, 100500)],
        (StakingModuleId(2), NodeOperatorId(2)): [v(11, 100500), v(12, 100500)],
        (StakingModuleId(3), NodeOperatorId(1)): [v(13, FAR_FUTURE_EPOCH), v(14, FAR_FUTURE_EPOCH)],
        (StakingModuleId(3), NodeOperatorId(2)): [v(15, FAR_FUTURE_EPOCH), v(16, FAR_FUTURE_EPOCH)],
    }
    recently_requested_to_exit_indices_per_operator = {
        (StakingModuleId(0), NodeOperatorId(1)): {1, 2},
        (StakingModuleId(0), NodeOperatorId(2)): {},
        (StakingModuleId(1), NodeOperatorId(1)): {5, 6},
        (StakingModuleId(1), NodeOperatorId(2)): {},
        (StakingModuleId(2), NodeOperatorId(1)): {9, 10},
        (StakingModuleId(2), NodeOperatorId(2)): {},
        (StakingModuleId(3), NodeOperatorId(1)): {13, 14},
        (StakingModuleId(3), NodeOperatorId(2)): {},
    }

    delayed = ValidatorsExit._get_delayed_validators_per_operator(
        object.__new__(ValidatorsExit),
        operator_validators,
        recently_requested_to_exit_indices_per_operator,
        last_requested_to_exit_indices_per_operator,
    )

    assert len(delayed) == 1
    assert delayed[(StakingModuleId(3), NodeOperatorId(2))] == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    ('exit_epoch', 'expected'),
    [(100500, True),
     (FAR_FUTURE_EPOCH, False)]
)
def test_is_on_exit(exit_epoch, expected):
    validator = object.__new__(Validator)
    validator.validator = object.__new__(ValidatorState)
    validator.validator.exit_epoch = exit_epoch
    assert ValidatorsExit._is_on_exit(validator) == expected
