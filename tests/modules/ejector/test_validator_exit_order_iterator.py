import math
from collections import Counter
from unittest.mock import Mock

import pytest

from src.constants import (
    CURATED_V1_MODULE_NAME,
    CURATED_V1_TYPE,
    CURATED_V2_MODULE_NAME,
    CURATED_V2_TYPE,
    FAR_FUTURE_EPOCH,
    MIN_ACTIVATION_BALANCE,
    SHARD_COMMITTEE_PERIOD,
)
from src.modules.oracles.ejector.data_encode import FWR_AMOUNT, MAX_PWR_AMOUNT
from src.providers.execution.contracts.meta_registry import ExternalOperator, SubNodeOperator
from src.services.exit_order_iterator import (
    InvalidCuratedModuleConfigError,
    NodeOperatorAlreadyGroupedError,
    NodeOperatorExpectedToBeInCMv1Error,
    NodeOperatorStats,
    StakingModuleStats,
    ValidatorExitIterator,
    WeightsNotUpdatedError,
    WithdrawalStep,
)
from src.services.validator_state import InFlightWithdrawals
from src.types import EpochNumber, Gwei, NodeOperatorId, StakingModuleId
from src.utils.validator_balance import get_predictable_inbound_balance
from src.web3py.extensions.lido_validators import NodeOperator, NodeOperatorLimitMode, StakingModule
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.meta_registry import OperatorGroupFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


@pytest.fixture
def iterator(web3):
    it = ValidatorExitIterator(web3, ReferenceBlockStampFactory.build())
    it.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[])
    it.w3.lido_validators.get_lido_node_operators = Mock(return_value=[])
    it.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={})
    it.w3.lido_validators.get_lido_validators_by_node_operators = Mock(return_value={})
    it.lvs.get_in_flight_withdrawals = Mock(return_value=InFlightWithdrawals())
    it.w3.cc.get_validators_by_indexes = Mock(return_value={})
    it.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=make_report_limits(max_balance_exit_requested_per_report_in_eth=100)
    )
    it.w3.lido_contracts.validators_exit_bus_oracle.get_max_requests_per_report = Mock(return_value=500)
    it.w3.lido_contracts.oracle_daemon_config.exit_iteration_chunk_eth = Mock(return_value=32)
    it.w3.lido_contracts.oracle_daemon_config.active_rebalancing_grace_period_epochs = Mock(return_value=0)
    it.w3.lido_contracts.staking_router.is_partial_withdrawals_allowed = Mock(return_value=False)
    it.w3.lido_contracts.triggerable_withdrawals_bus.get_unprocessed_intents = Mock(return_value=[])
    it.w3.cc.get_state_view = Mock(return_value=Mock(pending_partial_withdrawals=[]))
    it.w3.eth.contract = Mock()
    it._reset_iterator_data()
    it.max_exit_requests_per_report = 500
    it.exit_limit_in_gwei = Gwei(100_000 * 10**9)
    it.fwr_weight_by_wc_type = {1: Gwei(32 * 10**9), 2: Gwei(2048 * 10**9)}
    it.chunk = Gwei(32 * 10**9)
    it.in_flight = InFlightWithdrawals()
    return it


def make_report_limits(max_balance_exit_requested_per_report_in_eth=100, wc_type01=32, wc_type02=2048):
    return Mock(
        max_balance_exit_requested_per_report_in_eth=max_balance_exit_requested_per_report_in_eth,
        max_effective_balance_weight_wc_type01=wc_type01,
        max_effective_balance_weight_wc_type02=wc_type02,
    )


def selectable_bound(iterator) -> int:
    """Upper bound for `build_with_activation_epoch_bound` that keeps validators out of SHARD_COMMITTEE_PERIOD."""
    return iterator.blockstamp.ref_epoch - SHARD_COMMITTEE_PERIOD + 1


def make_staking_module(sm_id, threshold=10000, name="test", wc_type=1):
    return StakingModule(
        id=StakingModuleId(sm_id),
        staking_module_address="0x" + "1" * 40,
        staking_module_fee=0,
        treasury_fee=0,
        stake_share_limit=0,
        status=0,
        name=name,
        last_deposit_at=0,
        last_deposit_block=0,
        exited_validators_count=0,
        priority_exit_share_threshold=threshold,
        max_deposits_per_block=0,
        min_deposit_block_distance=0,
        withdrawal_credentials_type=wc_type,
        validators_balance_gwei=Gwei(0),
    )


def make_node_operator(no_id, sm, total_dep=0, target=0, limit_mode=NodeOperatorLimitMode.DISABLED):
    return NodeOperator(
        id=NodeOperatorId(no_id),
        staking_module=sm,
        is_active=True,
        is_target_limit_active=limit_mode,
        target_validators_count=target,
        refunded_validators_count=0,
        total_exited_validators=0,
        total_deposited_validators=total_dep,
        depositable_validators_count=0,
    )


@pytest.mark.unit
def test_eject_validator(iterator):
    sm1 = make_staking_module(1)
    no1 = make_node_operator(1, sm1, total_dep=3, target=1, limit_mode=NodeOperatorLimitMode.FORCE)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            gid11: [
                LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator)) for _ in range(3)
            ]
        }
    )
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()  # Skip contract calls
    iterator._calculate_sm_weights = Mock()  # Skip weight calculation

    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()

    assert iterator.node_operators_stats[gid11].predictable_validators == 3
    iterator._allocate(gid11, iterator.exitable_validators[gid11][0], FWR_AMOUNT)
    assert iterator.node_operators_stats[gid11].predictable_validators == 2


@pytest.mark.unit
def test_no_predicate(iterator):
    # total = 1000 vals worth of balance; threshold = 15% → max_allowed = 150 vals
    iterator.total_lido_predictable_balance = Gwei(1000 * 32 * 10**9)
    sm2 = make_staking_module(2, threshold=int(0.15 * 10000))
    no2 = make_node_operator(2, sm2)

    # sm2 has 200 vals' balance; excess above 150 = 50 vals' worth
    ms2 = StakingModuleStats(
        staking_module=sm2,
        predictable_balance=Gwei(200 * 32 * 10**9),
    )

    # force_exit_to=50, soft_exit_to=25, predictable_validators=2000 → both over target
    nos2 = NodeOperatorStats(
        node_operator=no2,
        module_stats=ms2,
        predictable_validators=2000,
        force_exit_to=50,
        soft_exit_to=25,
        predictable_balance=Gwei(200 * 32 * 10**9),
        total_stake=Gwei(200 * 32 * 10**9),
        weight=10.0,
    )

    iterator.exitable_validators = {
        (sm2.id, no2.id): [Mock(index=20)],
    }

    res2 = iterator._no_predicate(nos2, {(sm2.id, no2.id): 0.0})
    # force: -(2000 - 50) = -1950
    assert res2[0] == -(2000 - 50)
    # soft:  -(2000 - 25) = -1975
    assert res2[1] == -(2000 - 25)
    # share: -(200*32e9 - 150*32e9) = -(50 * 32e9)
    assert res2[2] == -(50 * 32 * 10**9)
    # target stake deviation, taken from the precomputed deviations
    assert res2[3] == 0
    # lowest validator index
    assert res2[4] == 20


@pytest.mark.unit
def test_no_force_and_soft_predicate(iterator):
    sm = make_staking_module(1)

    def make_stats(id_val, force, soft, pred):
        return NodeOperatorStats(
            node_operator=make_node_operator(id_val, sm),
            module_stats=Mock(),
            force_exit_to=force,
            soft_exit_to=soft,
            predictable_validators=pred,
        )

    nos = [make_stats(1, 10, 20, 20), make_stats(2, 5, 0, 5), make_stats(3, None, 20, 100), make_stats(4, 0, None, 4)]

    sorted_f = sorted(nos, key=lambda x: -iterator._no_force_predicate(x))
    assert [n.node_operator.id for n in sorted_f] == [
        NodeOperatorId(1),
        NodeOperatorId(4),
        NodeOperatorId(2),
        NodeOperatorId(3),
    ]

    # soft predicate values: NO1=0(20-20), NO2=5(5-0=5), NO3=80(100-20=80), NO4=0(4-None=0)
    sorted_s = sorted(nos, key=lambda x: -iterator._no_soft_predicate(x))
    assert [n.node_operator.id for n in sorted_s] == [
        NodeOperatorId(3),  # 80 excess
        NodeOperatorId(2),  # 5 excess
        NodeOperatorId(1),  # 0 (at target)
        NodeOperatorId(4),  # 0 (no soft limit)
    ]


@pytest.mark.unit
def test_lowest_validators_index_predicate(iterator):
    sm = make_staking_module(1)
    no1 = make_node_operator(1, sm)
    no2 = make_node_operator(2, sm)
    no3 = make_node_operator(3, sm)
    ms = StakingModuleStats(staking_module=sm)
    iterator.exitable_validators = {
        (sm.id, no1.id): [Mock(index=5)],
        (sm.id, no2.id): [Mock(index=10)],
        (sm.id, no3.id): [],
    }
    assert iterator._lowest_validator_index_predicate(NodeOperatorStats(no1, ms)) == 5
    assert iterator._lowest_validator_index_predicate(NodeOperatorStats(no2, ms)) == 10
    assert iterator._lowest_validator_index_predicate(NodeOperatorStats(no3, ms)) == 0


@pytest.mark.unit
def test_next__request_limit_reached__stops_iteration(iterator):
    """__next__ stops the iteration once max_exit_requests_per_report is reached."""
    sm1 = make_staking_module(1)
    no1 = make_node_operator(1, sm1, total_dep=3)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            gid11: [
                LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator)) for _ in range(3)
            ]
        }
    )
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()
    iterator._calculate_sm_weights = Mock()
    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()
    # These attributes are normally set by __iter__; set them manually for the test
    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)
    iterator.max_exit_requests_per_report = 2

    ejected = [next(iterator), next(iterator)]

    assert len(ejected) == 2
    assert len(iterator.get_requests()) == 2
    with pytest.raises(StopIteration):
        next(iterator)


@pytest.mark.unit
def test_allocate_forced_exits__request_limit_reached__stops_early(iterator):
    """allocate_forced_exits returns only the room left under max_exit_requests_per_report."""
    sm1 = make_staking_module(1)
    # force_exit_to=1, predictable_validators=4 → 3 forced candidates
    no1 = make_node_operator(1, sm1, total_dep=4, target=1, limit_mode=NodeOperatorLimitMode.FORCE)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            gid11: [
                LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator)) for _ in range(4)
            ]
        }
    )
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()
    iterator._calculate_sm_weights = Mock()
    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()
    # These attributes are normally set by __iter__; set them manually for the test
    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)
    iterator.max_exit_requests_per_report = 2
    # The demand loop already requested 1 validator with a total limit of 2
    next(iterator)

    forced = iterator.allocate_forced_exits()

    assert len(forced) == 1, "Only 1 slot is left under the request limit"
    assert len(iterator.get_requests()) == 2


@pytest.mark.unit
def test_allocate_forced_exits__force_target_exceeded__returns_excess(iterator):
    """Forced validators above their force exit target are returned by allocate_forced_exits."""
    sm1 = make_staking_module(1)
    no1 = make_node_operator(1, sm1, total_dep=3, target=1, limit_mode=NodeOperatorLimitMode.FORCE)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            gid11: [
                LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator)) for _ in range(3)
            ]
        }
    )
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()
    iterator._calculate_sm_weights = Mock()
    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()
    # These attributes are normally set by __iter__; set them manually for the test
    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

    # force_exit_to=1, predictable_validators=3 → 2 validators should be forcefully ejected
    forced = iterator.allocate_forced_exits()

    assert len(forced) == 2, "Expected 2 forced validators (3 validators, target 1)"
    assert all(step.gid == gid11 and step.amount == FWR_AMOUNT for step in forced)


@pytest.mark.unit
def test_allocate_forced_exits__below_target__returns_empty(iterator):
    """When all validators are at or below their force exit target, returns empty list."""
    sm1 = make_staking_module(1)
    # 1 exitable validator, force_exit_to=2 → force_predicate=max(1-2,0)=0, no exit needed
    no1 = make_node_operator(1, sm1, total_dep=1, target=2, limit_mode=NodeOperatorLimitMode.FORCE)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={gid11: [LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator))]}
    )
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()
    iterator._calculate_sm_weights = Mock()
    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()
    # These attributes are normally set by __iter__; set them manually for the test
    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

    forced = iterator.allocate_forced_exits()

    assert forced == [], "No forced exits needed when validators are below target"


def set_operators(iterator, module_id, operators, *, is_cm_v2=False):
    """Operators given as {no_id: (stake_eth, weight)}, with no validators behind them."""
    sm = make_staking_module(module_id)
    ms = StakingModuleStats(staking_module=sm, is_cm_v2=is_cm_v2)
    iterator.module_stats[sm.id] = ms
    for no_id, (stake_eth, weight) in operators.items():
        gid = (sm.id, NodeOperatorId(no_id))
        iterator.node_operators_stats[gid] = NodeOperatorStats(
            node_operator=make_node_operator(no_id, sm),
            module_stats=ms,
            total_stake=Gwei(stake_eth * 10**9),
            weight=float(weight),
        )
        iterator.exitable_validators[gid] = []
        iterator.first_activation_epoch[gid] = EpochNumber(0)
    return sm.id


@pytest.mark.unit
class TestTargetStakeDeviations:
    def test_get_target_stake_deviations__equal_weights__deviation_from_module_average(self, iterator):
        # Arrange: 100 + 300 = 400 ETH, equal weights → target 200 each
        sm_id = set_operators(iterator, 1, {1: (100, 1), 2: (300, 1)})

        # Act
        deviations = iterator._get_target_stake_deviations()

        # Assert
        assert deviations == {(sm_id, 1): -100 * 10**9, (sm_id, 2): 100 * 10**9}

    def test_get_target_stake_deviations__weights__target_follows_weight(self, iterator):
        # Arrange: 400 ETH, weights 3/1 → targets 300/100
        sm_id = set_operators(iterator, 1, {1: (100, 3), 2: (300, 1)})

        # Act
        deviations = iterator._get_target_stake_deviations()

        # Assert
        assert deviations == {(sm_id, 1): -200 * 10**9, (sm_id, 2): 200 * 10**9}

    def test_get_target_stake_deviations__zero_weights__deviation_is_own_stake(self, iterator):
        sm_id = set_operators(iterator, 1, {1: (100, 0), 2: (300, 0)})

        assert iterator._get_target_stake_deviations() == {(sm_id, 1): 100 * 10**9, (sm_id, 2): 300 * 10**9}

    def test_get_target_stake_deviations__modules__computed_per_module(self, iterator):
        # Arrange: module 1 is balanced, module 2 is not; the modules do not share a target
        sm1 = set_operators(iterator, 1, {1: (100, 1), 2: (100, 1)})
        sm2 = set_operators(iterator, 2, {3: (500, 1), 4: (100, 1)})

        # Act
        deviations = iterator._get_target_stake_deviations()

        # Assert
        assert deviations == {
            (sm1, 1): 0,
            (sm1, 2): 0,
            (sm2, 3): 200 * 10**9,
            (sm2, 4): -200 * 10**9,
        }

    def test_get_target_stake_deviations__cm_v2_grace_period__excluded_and_ranked_last(self, iterator):
        # Arrange: operator 3 activated 10 epochs ago, inside a 100-epoch grace period. The others share
        # 400 + 100 = 500 ETH → target 250.
        sm_id = set_operators(iterator, 2, {1: (400, 1), 2: (100, 1), 3: (1000, 1)}, is_cm_v2=True)
        iterator.first_activation_epoch[(sm_id, 3)] = EpochNumber(iterator.blockstamp.ref_epoch - 10)
        iterator.w3.lido_contracts.oracle_daemon_config.active_rebalancing_grace_period_epochs = Mock(return_value=100)

        # Act
        deviations = iterator._get_target_stake_deviations()

        # Assert
        assert deviations == {(sm_id, 1): 150 * 10**9, (sm_id, 2): -150 * 10**9, (sm_id, 3): -math.inf}

    def test_get_target_stake_deviations__cm_v2_in_flight_pwr__counted_out_of_stake(self, iterator):
        # Arrange: operator 1 holds 400 ETH with 300 ETH already requested as PWRs → 100/100
        sm_id = set_operators(iterator, 2, {1: (400, 1), 2: (100, 1)}, is_cm_v2=True)
        validator = make_validator(1, 400)
        iterator.exitable_validators[(sm_id, 1)] = [validator]
        iterator.in_flight = InFlightWithdrawals(pwr_amounts={validator.index: Gwei(300 * 10**9)})

        # Act / Assert
        assert iterator._get_target_stake_deviations() == {(sm_id, 1): 0, (sm_id, 2): 0}

    @pytest.mark.parametrize(
        ("grace_period_epochs", "expected_no_id"),
        [
            pytest.param(100, 2, id="new_operator_in_grace__ranked_last"),
            pytest.param(0, 1, id="no_grace__largest_excess_first"),
        ],
    )
    def test_next__cm_v2_new_operator__grace_period_decides_order(self, iterator, grace_period_epochs, expected_no_id):
        # Arrange: operator 1 holds 1000 ETH but activated 10 epochs ago; operator 2 holds 100 ETH
        setup_cmv2_operators(iterator, {1: ([make_validator(1, 1000)], 1), 2: ([make_validator(2, 100)], 1)})
        iterator.first_activation_epoch[gid_of(1)] = EpochNumber(iterator.blockstamp.ref_epoch - 10)
        iterator.w3.lido_contracts.oracle_daemon_config.active_rebalancing_grace_period_epochs = Mock(
            return_value=grace_period_epochs
        )

        # Act
        step = next(iterator)

        # Assert
        assert step.gid == gid_of(expected_no_id)


@pytest.mark.unit
def test_max_share_rate_coefficient_predicate(iterator):
    """_max_share_rate_coefficient_predicate orders modules by excess balance above their share threshold."""
    threshold = int(0.15 * 10000)  # 15%
    iterator.total_lido_predictable_balance = Gwei(3500 * 32 * 10**9)

    sm1 = make_staking_module(1, threshold=threshold)
    sm2 = make_staking_module(2, threshold=threshold)
    sm3 = make_staking_module(3, threshold=threshold)

    # SM1: balance 1000 vals, max allowed ~525 vals → positive excess
    # SM2: balance 200 vals, max allowed ~525 vals → under limit (negative)
    # SM3: balance 2000 vals, max allowed ~525 vals → higher positive excess
    ms1 = StakingModuleStats(staking_module=sm1, predictable_balance=Gwei(1000 * 32 * 10**9))
    ms2 = StakingModuleStats(staking_module=sm2, predictable_balance=Gwei(200 * 32 * 10**9))
    ms3 = StakingModuleStats(staking_module=sm3, predictable_balance=Gwei(2000 * 32 * 10**9))

    no1 = make_node_operator(1, sm1)
    no2 = make_node_operator(2, sm2)
    no3 = make_node_operator(3, sm3)

    nos = [
        NodeOperatorStats(node_operator=no1, module_stats=ms1),
        NodeOperatorStats(node_operator=no2, module_stats=ms2),
        NodeOperatorStats(node_operator=no3, module_stats=ms3),
    ]

    sorted_nos = sorted(nos, key=lambda x: -iterator._max_share_rate_coefficient_predicate(x))
    assert sorted_nos[0].node_operator.id == NodeOperatorId(3), "SM3 has highest excess balance above threshold"
    assert sorted_nos[1].node_operator.id == NodeOperatorId(1), "SM1 has moderate excess balance above threshold"
    assert sorted_nos[2].node_operator.id == NodeOperatorId(2), "SM2 is under threshold limit"


@pytest.mark.unit
def test_max_share_rate_coefficient_predicate_zero_balance(iterator):
    """_max_share_rate_coefficient_predicate returns -2 when module predictable_balance is zero."""
    sm = make_staking_module(1)
    ms = StakingModuleStats(staking_module=sm, predictable_balance=Gwei(0))
    no = make_node_operator(1, sm)
    nos = NodeOperatorStats(node_operator=no, module_stats=ms)

    result = iterator._max_share_rate_coefficient_predicate(nos)
    assert result == -2


@pytest.mark.unit
class TestProcessGroup:
    @staticmethod
    def _make_ext_data(sm_id, no_id):
        return bytes([0, sm_id]) + no_id.to_bytes(8, byteorder='big')

    def test_process_group__two_internal_two_external__external_stake_to_cm_v2_weight_to_cm_v1(self, iterator):
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        no_int1 = make_node_operator(10, sm_v2)
        no_int2 = make_node_operator(11, sm_v2)
        nos_int1 = NodeOperatorStats(
            node_operator=no_int1,
            module_stats=ms_v2,
            predictable_balance=Gwei(100 * 10**9),
            weight=4.0,
        )
        nos_int2 = NodeOperatorStats(
            node_operator=no_int2,
            module_stats=ms_v2,
            predictable_balance=Gwei(200 * 10**9),
            weight=6.0,
        )
        no_ext1 = make_node_operator(20, sm_v1)
        no_ext2 = make_node_operator(21, sm_v1)
        nos_ext1 = NodeOperatorStats(
            node_operator=no_ext1,
            module_stats=ms_v1,
            predictable_balance=Gwei(50 * 10**9),
        )
        nos_ext2 = NodeOperatorStats(
            node_operator=no_ext2,
            module_stats=ms_v1,
            predictable_balance=Gwei(30 * 10**9),
        )
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            (sm_v2.id, no_int1.id): nos_int1,
            (sm_v2.id, no_int2.id): nos_int2,
            (sm_v1.id, no_ext1.id): nos_ext1,
            (sm_v1.id, no_ext2.id): nos_ext2,
        }
        group = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no_int1.id, share=50),
                SubNodeOperator(node_operator_id=no_int2.id, share=50),
            ],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext1.id)),
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext2.id)),
            ],
        )

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        iterator._process_group(group, cm_v1, cm_v2)

        assert nos_int1.internal_operator_group is not None
        assert nos_int2.internal_operator_group is not None
        assert nos_ext1.external_operator_group is not None
        assert nos_ext2.external_operator_group is not None
        # CMv1 operators keep their own stake (externalStake = 0 outside CMv2)
        assert nos_ext1.total_stake == 0
        assert nos_ext2.total_stake == 0
        # internal_weight = 4.0 + 6.0 = 10.0, split equally among 2 externals = 5.0 each
        assert nos_ext1.weight == 5.0
        assert nos_ext2.weight == 5.0
        # int1 gets external_balance * 4.0/10.0 = 80 * 0.4 = 32
        assert nos_int1.total_stake == Gwei(32 * 10**9)
        # int2 gets external_balance * 6.0/10.0 = 80 * 0.6 = 48
        assert nos_int2.total_stake == Gwei(48 * 10**9)

    def test_process_group__already_grouped_internal__raises_error(self, iterator):
        """Error raised when a sub_node_operator already belongs to a group,
        even when the group also contains valid external_operators on the other side."""
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)

        # Internal NO (CMv2) is already in a group
        no_int = make_node_operator(1, sm_v2)
        nos_int = NodeOperatorStats(node_operator=no_int, module_stats=ms_v2, internal_operator_group=Mock())

        # External NO (CMv1) is fresh — not yet in any group
        no_ext = make_node_operator(2, sm_v1)
        nos_ext = NodeOperatorStats(node_operator=no_ext, module_stats=ms_v1)

        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            (sm_v2.id, no_int.id): nos_int,
            (sm_v1.id, no_ext.id): nos_ext,
        }

        # Group has the already-grouped NO in sub_node_operators AND a valid external NO
        group = OperatorGroupFactory.build(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        with pytest.raises(NodeOperatorAlreadyGroupedError):
            iterator._process_group(group, cm_v1, cm_v2)

        # Same NO in external and internal
        group = OperatorGroupFactory.build(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v2.id, no_int.id))],
        )

        with pytest.raises(NodeOperatorExpectedToBeInCMv1Error):
            iterator._process_group(group, cm_v1, cm_v2)

    def test_process_group__zero_internal_weight__distributes_external_balance_by_share(self, iterator):
        """When all internal NOs have weight 0, external balance is distributed by operator share."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        no_int1 = make_node_operator(10, sm_v2)
        no_int2 = make_node_operator(11, sm_v2)
        nos_int1 = NodeOperatorStats(node_operator=no_int1, module_stats=ms_v2, weight=0)
        nos_int2 = NodeOperatorStats(node_operator=no_int2, module_stats=ms_v2, weight=0)
        no_ext1 = make_node_operator(20, sm_v1)
        no_ext2 = make_node_operator(21, sm_v1)
        nos_ext1 = NodeOperatorStats(
            node_operator=no_ext1,
            module_stats=ms_v1,
            predictable_balance=Gwei(50 * 10**9),
        )
        nos_ext2 = NodeOperatorStats(
            node_operator=no_ext2,
            module_stats=ms_v1,
            predictable_balance=Gwei(30 * 10**9),
        )
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            (sm_v2.id, no_int1.id): nos_int1,
            (sm_v2.id, no_int2.id): nos_int2,
            (sm_v1.id, no_ext1.id): nos_ext1,
            (sm_v1.id, no_ext2.id): nos_ext2,
        }
        group = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no_int1.id, share=4_000),
                SubNodeOperator(node_operator_id=no_int2.id, share=6_000),
            ],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext1.id)),
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext2.id)),
            ],
        )

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        iterator._process_group(group, cm_v1, cm_v2)

        # external_balance = 50 + 30 = 80, distributed by shares 40% and 60%.
        assert nos_int1.total_stake == Gwei(32 * 10**9)
        assert nos_int2.total_stake == Gwei(48 * 10**9)
        assert nos_int1.total_stake + nos_int2.total_stake == Gwei(80 * 10**9)

    def test_process_group__already_grouped_external__raises_error(self, iterator):
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        no_ext = make_node_operator(5, sm_v1)
        nos_ext = NodeOperatorStats(node_operator=no_ext, module_stats=ms_v1, external_operator_group=Mock())
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {(sm_v1.id, no_ext.id): nos_ext}
        group = OperatorGroupFactory.build(
            sub_node_operators=[],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        with pytest.raises(NodeOperatorAlreadyGroupedError):
            iterator._process_group(group, cm_v1, cm_v2)


@pytest.mark.unit
class TestEjectValidatorTotalStake:
    def test_eject_validator__single_validator__decrements_total_stake(self, iterator):
        sm = make_staking_module(1)
        no = make_node_operator(1, sm, total_dep=2, target=1, limit_mode=NodeOperatorLimitMode.FORCE)
        gid = (sm.id, no.id)
        initial_stake = Gwei(64 * 10**9)
        ms = StakingModuleStats(
            staking_module=sm,
            predictable_balance=initial_stake,
        )
        nos = NodeOperatorStats(
            node_operator=no,
            module_stats=ms,
            predictable_validators=2,
            predictable_balance=initial_stake,
            total_stake=initial_stake,
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator))
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.total_lido_predictable_balance = initial_stake
        iterator.exitable_validators = {gid: [validator]}

        exit_balance = get_predictable_inbound_balance(validator)

        iterator._allocate(gid, validator, FWR_AMOUNT)

        assert ms.predictable_balance == initial_stake - exit_balance
        assert nos.total_stake == initial_stake - exit_balance


@pytest.mark.unit
class TestIsValidatorExitable:
    def test_is_validator_exitable__active_validator__exitable(self, iterator):
        active_validator = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
        )

        assert iterator._is_validator_exitable(active_validator) is True

    def test_is_validator_exitable__on_exit__not_exitable(self, iterator):
        on_exit_validator = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=100),
        )

        assert iterator._is_validator_exitable(on_exit_validator) is False

    def test_is_validator_exitable__consolidating_as_source__not_exitable(self, iterator):
        consolidating_validator = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
            consolidating_as_source=Mock(),
        )

        assert iterator._is_validator_exitable(consolidating_validator) is False


@pytest.mark.unit
class TestGetExpectedValidatorsDiff:
    def test_get_expected_validators_diff__current_above_expected__returns_diff(self):
        assert ValidatorExitIterator._get_expected_validators_diff(10, 5) == 5

    def test_get_expected_validators_diff__current_equal_expected__returns_zero(self):
        assert ValidatorExitIterator._get_expected_validators_diff(5, 5) == 0

    def test_get_expected_validators_diff__current_below_expected__returns_zero(self):
        assert ValidatorExitIterator._get_expected_validators_diff(3, 5) == 0

    def test_get_expected_validators_diff__expected_none__returns_zero(self):
        assert ValidatorExitIterator._get_expected_validators_diff(10, None) == 0


@pytest.mark.unit
class TestNoRemainingForcedPredicate:
    def test_no_remaining_forced_predicate__orders_by_force_then_index(self, iterator):
        sm = make_staking_module(1)
        ms = StakingModuleStats(staking_module=sm)
        no1 = make_node_operator(1, sm)
        no2 = make_node_operator(2, sm)
        nos1 = NodeOperatorStats(
            node_operator=no1,
            module_stats=ms,
            predictable_validators=10,
            force_exit_to=5,
        )
        nos2 = NodeOperatorStats(
            node_operator=no2,
            module_stats=ms,
            predictable_validators=10,
            force_exit_to=2,
        )
        iterator.exitable_validators = {
            (sm.id, no1.id): [Mock(index=100)],
            (sm.id, no2.id): [Mock(index=50)],
        }

        sorted_nos = sorted([nos1, nos2], key=iterator.no_remaining_forced_predicate)
        assert sorted_nos[0].node_operator.id == no2.id, "NO2 has more forced excess (8 vs 5)"
        assert sorted_nos[1].node_operator.id == no1.id


@pytest.mark.unit
class TestFetchCuratedModules:
    def test_fetch_curated_modules__both_found__returns_tuple(self, iterator):
        sm1 = make_staking_module(1, name=CURATED_V1_MODULE_NAME)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2, name=CURATED_V2_MODULE_NAME)
        sm2.staking_module_address = "0x" + "b" * 40
        ms1 = StakingModuleStats(staking_module=sm1)
        ms2 = StakingModuleStats(staking_module=sm2)
        iterator.module_stats = {sm1.id: ms1, sm2.id: ms2}

        mock_contract_v1 = Mock()
        mock_contract_v1.get_type.return_value = CURATED_V1_TYPE
        mock_contract_v2 = Mock()
        mock_contract_v2.get_type.return_value = CURATED_V2_TYPE

        contracts_by_addr = {
            sm1.staking_module_address: mock_contract_v1,
            sm2.staking_module_address: mock_contract_v2,
        }
        iterator.w3.eth.contract = Mock(side_effect=lambda **kw: contracts_by_addr[kw['address']])

        cm_v1, cm_v2 = iterator._fetch_curated_modules()

        assert cm_v1[0] == sm1.id
        assert cm_v2[0] == sm2.id

    def test_fetch_curated_modules__missing_v2__raises_error(self, iterator):
        sm1 = make_staking_module(1, name=CURATED_V1_MODULE_NAME)
        ms1 = StakingModuleStats(staking_module=sm1)
        iterator.module_stats = {sm1.id: ms1}

        mock_contract = Mock()
        mock_contract.get_type.return_value = CURATED_V1_TYPE
        iterator.w3.eth.contract = Mock(return_value=mock_contract)

        with pytest.raises(InvalidCuratedModuleConfigError):
            iterator._fetch_curated_modules()

    def test_fetch_curated_modules__missing_v1__raises_error(self, iterator):
        sm1 = make_staking_module(1, name=CURATED_V2_MODULE_NAME)
        ms1 = StakingModuleStats(staking_module=sm1)
        iterator.module_stats = {sm1.id: ms1}

        mock_contract = Mock()
        mock_contract.get_type.return_value = CURATED_V2_TYPE
        iterator.w3.eth.contract = Mock(return_value=mock_contract)

        with pytest.raises(InvalidCuratedModuleConfigError):
            iterator._fetch_curated_modules()


@pytest.mark.unit
class TestSetupWeights:
    def test_setup_weights__assigns_weights_to_node_operators(self, iterator):
        sm = make_staking_module(2)
        ms = StakingModuleStats(staking_module=sm)
        no1 = make_node_operator(1, sm)
        no2 = make_node_operator(2, sm)
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {
            (sm.id, no1.id): NodeOperatorStats(node_operator=no1, module_stats=ms),
            (sm.id, no2.id): NodeOperatorStats(node_operator=no2, module_stats=ms),
        }

        mock_contract = Mock()
        mock_contract.get_node_operator_deposit_info_to_update_count.return_value = 0
        mock_contract.get_operator_weights.return_value = [3.0, 7.0]

        iterator._setup_weights((sm.id, mock_contract))

        assert iterator.node_operators_stats[(sm.id, no1.id)].weight == 3.0
        assert iterator.node_operators_stats[(sm.id, no2.id)].weight == 7.0

    def test_setup_weights__not_updated__raises_error(self, iterator):
        sm = make_staking_module(2)
        ms = StakingModuleStats(staking_module=sm)
        no1 = make_node_operator(1, sm)
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {
            (sm.id, no1.id): NodeOperatorStats(node_operator=no1, module_stats=ms),
        }

        mock_contract = Mock()
        mock_contract.get_node_operator_deposit_info_to_update_count.return_value = 5

        with pytest.raises(WeightsNotUpdatedError):
            iterator._setup_weights((sm.id, mock_contract))


@pytest.mark.unit
class TestSetupMetaConnections:
    def test_setup_meta_connections__calls_process_group_for_each_group(self, iterator):
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)

        mock_contract = Mock()
        mock_contract.get_meta_registry_address.return_value = "0x" + "a" * 40

        mock_meta_registry = Mock()
        group1 = Mock()
        group2 = Mock()
        mock_meta_registry.get_all_groups.return_value = [group1, group2]

        iterator.w3.eth.contract = Mock(return_value=mock_meta_registry)
        iterator._process_group = Mock()

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, mock_contract)
        iterator._setup_meta_connections(cm_v1, cm_v2)

        assert iterator._process_group.call_count == 2
        iterator._process_group.assert_any_call(group1, cm_v1, cm_v2)
        iterator._process_group.assert_any_call(group2, cm_v1, cm_v2)


@pytest.mark.unit
class TestProcessGroupExternalNotInCMv1:
    @staticmethod
    def _make_ext_data(sm_id, no_id):
        return bytes([0, sm_id]) + no_id.to_bytes(8, byteorder='big')

    def test_process_group__external_not_in_cm_v1__raises_error(self, iterator):
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        sm_other = make_staking_module(3)
        ms_other = StakingModuleStats(staking_module=sm_other)
        no_ext = make_node_operator(5, sm_other)
        nos_ext = NodeOperatorStats(node_operator=no_ext, module_stats=ms_other)
        iterator.module_stats = {sm_v2.id: StakingModuleStats(staking_module=sm_v2), sm_other.id: ms_other}
        iterator.node_operators_stats = {(sm_other.id, no_ext.id): nos_ext}
        group = OperatorGroupFactory.build(
            sub_node_operators=[],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_other.id, no_ext.id))],
        )

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        with pytest.raises(NodeOperatorExpectedToBeInCMv1Error):
            iterator._process_group(group, cm_v1, cm_v2)


@pytest.mark.unit
class TestOperatorGroupIsFulfilled:
    def test_is_fulfilled__both_non_empty__returns_true(self):
        group = OperatorGroupFactory.build(
            sub_node_operators=[SubNodeOperator(node_operator_id=NodeOperatorId(1), share=100)],
            external_operators=[ExternalOperator(data=bytes(10))],
        )
        assert group.has_connection() is True

    def test_is_fulfilled__empty_sub_operators__returns_false(self):
        group = OperatorGroupFactory.build(
            sub_node_operators=[],
            external_operators=[ExternalOperator(data=bytes(10))],
        )
        assert group.has_connection() is False

    def test_is_fulfilled__empty_external_operators__returns_false(self):
        group = OperatorGroupFactory.build(
            sub_node_operators=[SubNodeOperator(node_operator_id=NodeOperatorId(1), share=100)],
            external_operators=[],
        )
        assert group.has_connection() is False

    def test_is_fulfilled__both_empty__returns_false(self):
        group = OperatorGroupFactory.build(
            sub_node_operators=[],
            external_operators=[],
        )
        assert group.has_connection() is False


@pytest.mark.unit
class TestInvalidCuratedModuleConfigError:
    def test_fetch_curated_modules__duplicate_curated_name__raises_error(self, iterator):
        sm1 = make_staking_module(1, name=CURATED_V1_MODULE_NAME)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2, name=CURATED_V1_MODULE_NAME)
        sm2.staking_module_address = "0x" + "b" * 40
        sm3 = make_staking_module(3, name=CURATED_V2_MODULE_NAME)
        sm3.staking_module_address = "0x" + "c" * 40
        iterator.module_stats = {
            sm1.id: StakingModuleStats(staking_module=sm1),
            sm2.id: StakingModuleStats(staking_module=sm2),
            sm3.id: StakingModuleStats(staking_module=sm3),
        }

        mock_contract_v1 = Mock()
        mock_contract_v1.get_type.return_value = CURATED_V1_TYPE
        mock_contract_v2 = Mock()
        mock_contract_v2.get_type.return_value = CURATED_V2_TYPE
        contracts_by_addr = {
            sm1.staking_module_address: mock_contract_v1,
            sm2.staking_module_address: mock_contract_v1,
            sm3.staking_module_address: mock_contract_v2,
        }
        iterator.w3.eth.contract = Mock(side_effect=lambda **kw: contracts_by_addr[kw['address']])

        with pytest.raises(InvalidCuratedModuleConfigError, match="curated-onchain-v1"):
            iterator._fetch_curated_modules()

    def test_fetch_curated_modules__simple_dvt_present__returns_curated_as_v1(self, iterator):
        sm1 = make_staking_module(1, name=CURATED_V1_MODULE_NAME)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2, name="SimpleDVT")
        sm2.staking_module_address = "0x" + "b" * 40
        sm3 = make_staking_module(3, name=CURATED_V2_MODULE_NAME)
        sm3.staking_module_address = "0x" + "c" * 40
        iterator.module_stats = {
            sm1.id: StakingModuleStats(staking_module=sm1),
            sm2.id: StakingModuleStats(staking_module=sm2),
            sm3.id: StakingModuleStats(staking_module=sm3),
        }

        mock_contract_v1 = Mock()
        mock_contract_v1.get_type.return_value = CURATED_V1_TYPE
        mock_contract_v2 = Mock()
        mock_contract_v2.get_type.return_value = CURATED_V2_TYPE
        contracts_by_addr = {
            sm1.staking_module_address: mock_contract_v1,
            sm2.staking_module_address: mock_contract_v1,
            sm3.staking_module_address: mock_contract_v2,
        }
        iterator.w3.eth.contract = Mock(side_effect=lambda **kw: contracts_by_addr[kw['address']])

        cm_v1, cm_v2 = iterator._fetch_curated_modules()

        assert cm_v1[0] == sm1.id
        assert cm_v2[0] == sm3.id

    def test_fetch_curated_modules__duplicate_v2__raises_error(self, iterator):
        sm1 = make_staking_module(1, name=CURATED_V1_MODULE_NAME)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2, name=CURATED_V2_MODULE_NAME)
        sm2.staking_module_address = "0x" + "b" * 40
        sm3 = make_staking_module(3, name=CURATED_V2_MODULE_NAME)
        sm3.staking_module_address = "0x" + "c" * 40
        iterator.module_stats = {
            sm1.id: StakingModuleStats(staking_module=sm1),
            sm2.id: StakingModuleStats(staking_module=sm2),
            sm3.id: StakingModuleStats(staking_module=sm3),
        }

        mock_contract_v1 = Mock()
        mock_contract_v1.get_type.return_value = CURATED_V1_TYPE
        mock_contract_v2 = Mock()
        mock_contract_v2.get_type.return_value = CURATED_V2_TYPE
        contracts_by_addr = {
            sm1.staking_module_address: mock_contract_v1,
            sm2.staking_module_address: mock_contract_v2,
            sm3.staking_module_address: mock_contract_v2,
        }
        iterator.w3.eth.contract = Mock(side_effect=lambda **kw: contracts_by_addr[kw['address']])

        with pytest.raises(InvalidCuratedModuleConfigError, match="curated module v2"):
            iterator._fetch_curated_modules()


@pytest.mark.unit
class TestDecreaseAffectedStake:
    @staticmethod
    def _make_ext_data(sm_id, no_id):
        return bytes([0, sm_id]) + no_id.to_bytes(8, byteorder='big')

    def test_no_group__only_decreases_own_stake(self, iterator):
        sm = make_staking_module(1)
        ms = StakingModuleStats(staking_module=sm)
        no = make_node_operator(1, sm)
        nos = NodeOperatorStats(node_operator=no, module_stats=ms, total_stake=Gwei(60 * 10**9))
        gid = (sm.id, no.id)
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}

        iterator._decrease_affected_stake(gid, Gwei(32 * 10**9))

        assert nos.total_stake == Gwei(28 * 10**9)

    def test_internal_exit__cm_v1_operators_untouched(self, iterator):
        """A CMv2 exit does not reach the CMv1 operators of the group: their stake is their own."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, is_cm_v2=True)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)

        no_int = make_node_operator(10, sm_v2)
        no_ext1 = make_node_operator(20, sm_v1)
        no_ext2 = make_node_operator(21, sm_v1)

        group = OperatorGroupFactory.build(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext1.id)),
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext2.id)),
            ],
        )
        nos_int = NodeOperatorStats(
            node_operator=no_int, module_stats=ms_v2, total_stake=Gwei(100 * 10**9), internal_operator_group=group
        )
        nos_ext1 = NodeOperatorStats(node_operator=no_ext1, module_stats=ms_v1, total_stake=Gwei(50 * 10**9))
        nos_ext2 = NodeOperatorStats(node_operator=no_ext2, module_stats=ms_v1, total_stake=Gwei(30 * 10**9))

        gid_int = (sm_v2.id, no_int.id)
        iterator.cm_v2_id = sm_v2.id
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            gid_int: nos_int,
            (sm_v1.id, no_ext1.id): nos_ext1,
            (sm_v1.id, no_ext2.id): nos_ext2,
        }

        iterator._decrease_affected_stake(gid_int, Gwei(32 * 10**9))

        assert nos_int.total_stake == Gwei(68 * 10**9)
        assert nos_ext1.total_stake == Gwei(50 * 10**9)
        assert nos_ext2.total_stake == Gwei(30 * 10**9)

    def test_external_exit__propagates_to_internal_operators_by_weight(self, iterator):
        """A CMv1 exit lowers the external stake share of the group's CMv2 operators, by weight."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, is_cm_v2=True)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)

        no_ext = make_node_operator(20, sm_v1)
        no_int1 = make_node_operator(10, sm_v2)
        no_int2 = make_node_operator(11, sm_v2)

        group = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no_int1.id, share=50),
                SubNodeOperator(node_operator_id=no_int2.id, share=50),
            ],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )
        nos_ext = NodeOperatorStats(
            node_operator=no_ext, module_stats=ms_v1, total_stake=Gwei(100 * 10**9), external_operator_group=group
        )
        nos_int1 = NodeOperatorStats(
            node_operator=no_int1, module_stats=ms_v2, total_stake=Gwei(80 * 10**9), weight=4.0
        )
        nos_int2 = NodeOperatorStats(
            node_operator=no_int2, module_stats=ms_v2, total_stake=Gwei(120 * 10**9), weight=6.0
        )

        gid_ext = (sm_v1.id, no_ext.id)
        iterator.cm_v2_id = sm_v2.id
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            gid_ext: nos_ext,
            (sm_v2.id, no_int1.id): nos_int1,
            (sm_v2.id, no_int2.id): nos_int2,
        }

        iterator._decrease_affected_stake(gid_ext, Gwei(50 * 10**9))

        assert nos_ext.total_stake == Gwei(50 * 10**9)
        # weights 4 and 6 of 10: 20 and 30 ETH of the 50 ETH exit
        assert nos_int1.total_stake == Gwei(60 * 10**9)
        assert nos_int2.total_stake == Gwei(90 * 10**9)

    def test_decrease_affected_stake__fractional_weights__consistent_total_and_deterministic_order(self, iterator):
        """Fractional weight splits must conserve the exit balance within float dust and keep the order stable."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, predictable_balance=Gwei(300 * 10**9))
        ms_v1 = StakingModuleStats(staking_module=sm_v1, predictable_balance=Gwei(300 * 10**9))

        no_ext = make_node_operator(20, sm_v1)
        internal = [make_node_operator(no_id, sm_v2) for no_id in (10, 11, 12)]
        group = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no.id, share=share)
                for no, share in zip(internal, (3333, 3333, 3334), strict=True)
            ],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )

        nos_ext = NodeOperatorStats(
            node_operator=no_ext,
            module_stats=ms_v1,
            total_stake=Gwei(100 * 10**9),
            predictable_balance=Gwei(100 * 10**9),
            weight=1.0,
            external_operator_group=group,
        )
        nos_internal = [
            NodeOperatorStats(
                node_operator=no,
                module_stats=ms_v2,
                total_stake=Gwei(100 * 10**9),
                predictable_balance=Gwei(100 * 10**9),
                weight=1.0,
            )
            for no in internal
        ]

        gid_ext = (sm_v1.id, no_ext.id)
        iterator.cm_v2_id = sm_v2.id
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {gid_ext: nos_ext} | {(sm_v2.id, n.node_operator.id): n for n in nos_internal}
        iterator.exitable_validators = {gid: [] for gid in iterator.node_operators_stats}
        iterator.total_lido_predictable_balance = Gwei(600 * 10**9)

        exit_balance = Gwei(100 * 10**9)  # 100 / 3 does not divide evenly among three internal NOs
        before = sum(n.total_stake for n in nos_internal)

        iterator._decrease_affected_stake(gid_ext, exit_balance)

        after = sum(n.total_stake for n in nos_internal)
        assert abs((before - after) - exit_balance) < 1

        def order():
            deviations = iterator._get_target_stake_deviations()
            return [
                (s.node_operator.staking_module.id, s.node_operator.id)
                for s in sorted(
                    iterator.node_operators_stats.values(), key=lambda no: iterator._no_predicate(no, deviations)
                )
            ]

        assert order() == order()

    def test_external_exit__zero_total_weight__decreases_internal_stake_by_share(self, iterator):
        """When all internal NO weights are 0, their stake decreases by operator share."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, is_cm_v2=True)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)

        no_ext = make_node_operator(20, sm_v1)
        no_int1 = make_node_operator(10, sm_v2)
        no_int2 = make_node_operator(11, sm_v2)
        group = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no_int1.id, share=4_000),
                SubNodeOperator(node_operator_id=no_int2.id, share=6_000),
            ],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )
        nos_ext = NodeOperatorStats(
            node_operator=no_ext, module_stats=ms_v1, total_stake=Gwei(100 * 10**9), external_operator_group=group
        )
        nos_int1 = NodeOperatorStats(node_operator=no_int1, module_stats=ms_v2, total_stake=Gwei(80 * 10**9), weight=0)
        nos_int2 = NodeOperatorStats(node_operator=no_int2, module_stats=ms_v2, total_stake=Gwei(120 * 10**9), weight=0)

        gid_ext = (sm_v1.id, no_ext.id)
        iterator.cm_v2_id = sm_v2.id
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            gid_ext: nos_ext,
            (sm_v2.id, no_int1.id): nos_int1,
            (sm_v2.id, no_int2.id): nos_int2,
        }

        iterator._decrease_affected_stake(gid_ext, Gwei(50 * 10**9))

        # total weight 0, so the 50 ETH exit is split by shares: 20 ETH and 30 ETH
        assert nos_int1.total_stake == Gwei(60 * 10**9)
        assert nos_int2.total_stake == Gwei(90 * 10**9)

    def test_external_exit__unfulfilled_group__no_cross_module_propagation(self, iterator):
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, is_cm_v2=True)

        no_ext = make_node_operator(20, sm_v1)
        no_int = make_node_operator(10, sm_v2)
        unfulfilled_group = OperatorGroupFactory.build(sub_node_operators=[], external_operators=[])
        nos_ext = NodeOperatorStats(
            node_operator=no_ext,
            module_stats=ms_v1,
            total_stake=Gwei(100 * 10**9),
            external_operator_group=unfulfilled_group,
        )
        nos_int = NodeOperatorStats(node_operator=no_int, module_stats=ms_v2, total_stake=Gwei(200 * 10**9))
        gid = (sm_v1.id, no_ext.id)
        iterator.module_stats = {sm_v1.id: ms_v1, sm_v2.id: ms_v2}
        iterator.node_operators_stats = {gid: nos_ext, (sm_v2.id, no_int.id): nos_int}
        iterator.cm_v2_id = sm_v2.id

        iterator._decrease_affected_stake(gid, Gwei(32 * 10**9))

        assert nos_ext.total_stake == Gwei(68 * 10**9)
        assert nos_int.total_stake == Gwei(200 * 10**9), "CMv2 not affected when the group is unfulfilled"


@pytest.mark.unit
class TestProcessGroupUnfulfilled:
    def test_process_group__only_internal__marks_grouped_but_no_cross_accounting(self, iterator):
        """A group with only sub_node_operators (no external) should mark them but not redistribute."""
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)
        no1 = make_node_operator(10, sm_v2)
        nos1 = NodeOperatorStats(
            node_operator=no1,
            module_stats=ms_v2,
            predictable_balance=Gwei(100 * 10**9),
            weight=5.0,
        )
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: StakingModuleStats(staking_module=sm_v1)}
        iterator.node_operators_stats = {(sm_v2.id, no1.id): nos1}

        group = OperatorGroupFactory.build(
            sub_node_operators=[SubNodeOperator(node_operator_id=no1.id, share=100)],
            external_operators=[],
        )
        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        iterator._process_group(group, cm_v1, cm_v2)

        # Internal NO should be marked grouped
        assert nos1.internal_operator_group is not None
        # No external stake to share
        assert nos1.total_stake == Gwei(0)


@pytest.mark.unit
class TestFinalizeAndReportLimits:
    def test_finalize_cm_v1_and_cm_v2_stats__sets_cm_v2_id(self, iterator):
        """_finalize_cm_v1_and_cm_v2_stats records the cm_v2 module id and marks only that module as CMv2."""
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        iterator.module_stats = {
            sm_v1.id: StakingModuleStats(staking_module=sm_v1),
            sm_v2.id: StakingModuleStats(staking_module=sm_v2),
        }

        iterator._fetch_curated_modules = Mock(return_value=(cm_v1, cm_v2))
        iterator._setup_weights = Mock()
        iterator._setup_meta_connections = Mock()

        iterator._finalize_cm_v1_and_cm_v2_stats()

        assert iterator.cm_v2_id == sm_v2.id
        assert iterator.module_stats[sm_v2.id].is_cm_v2
        assert not iterator.module_stats[sm_v1.id].is_cm_v2
        iterator._setup_weights.assert_called_once_with(cm_v2)
        iterator._setup_meta_connections.assert_called_once_with(cm_v1, cm_v2)

    def test_get_report_limits__sets_exit_limit_in_gwei(self, iterator):
        """_get_report_limits sets exit_limit_in_gwei from oracle report limits."""
        iterator.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits.return_value = (
            make_report_limits(max_balance_exit_requested_per_report_in_eth=100)
        )
        iterator._get_report_limits()

        assert iterator.exit_limit_in_gwei == Gwei(100 * 10**9)

    def test_get_report_limits__fwr_weights_and_chunk__read_from_contracts(self, iterator):
        iterator.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits.return_value = (
            make_report_limits(wc_type01=31, wc_type02=2000)
        )
        iterator.w3.lido_contracts.oracle_daemon_config.exit_iteration_chunk_eth.return_value = 64

        iterator._get_report_limits()

        assert iterator.fwr_weight_by_wc_type == {1: Gwei(31 * 10**9), 2: Gwei(2000 * 10**9)}
        assert iterator.chunk == Gwei(64 * 10**9)
        iterator.w3.lido_contracts.oracle_daemon_config.exit_iteration_chunk_eth.assert_called_once_with(
            iterator.blockstamp.block_hash
        )

    def test_get_report_limits__wo_value_set__uses_wo_value(self, iterator):
        vebo = iterator.w3.lido_contracts.validators_exit_bus_oracle
        vebo.get_max_requests_per_report.return_value = 300

        iterator._get_report_limits()

        assert iterator.max_exit_requests_per_report == 300
        vebo.get_max_requests_per_report.assert_called_once_with(iterator.blockstamp.block_hash)

    def test_get_report_limits__wo_value_zero__disables_exits(self, iterator):
        iterator.w3.lido_contracts.validators_exit_bus_oracle.get_max_requests_per_report.return_value = 0

        iterator._get_report_limits()

        assert iterator.max_exit_requests_per_report == 0


@pytest.mark.unit
class TestCalculatePendingValidatorClBalance:
    def test_pending_validators__updates_module_and_no_stats(self, iterator):
        """_calculate_pending_validator_cl_balance adds pending balance to module and NO stats."""
        from src.constants import MAX_EFFECTIVE_BALANCE

        sm = make_staking_module(1)
        no = make_node_operator(1, sm)
        gid = (sm.id, no.id)
        ms = StakingModuleStats(staking_module=sm)
        nos = NodeOperatorStats(node_operator=no, module_stats=ms, predictable_validators=0)

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.total_lido_predictable_balance = Gwei(0)

        deposit_amount = MAX_EFFECTIVE_BALANCE  # 32 ETH in Gwei
        # withdrawal_credentials is a hex string; '0x01' prefix indicates ETH1 withdrawal credentials
        deposit = Mock(amount=deposit_amount, withdrawal_credentials='0x01' + '00' * 28)

        lido_key = Mock(module_address="0x" + "a" * 40, operator_index=no.id)
        iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={"key1": (lido_key, [deposit])})
        iterator.w3.lido_contracts.staking_router.get_staking_modules_by_address = Mock(
            return_value={lido_key.module_address: sm}
        )

        iterator._calculate_pending_validator_cl_balance()

        expected_balance = Gwei(deposit_amount)
        assert iterator.total_lido_predictable_balance == expected_balance
        assert ms.predictable_balance == expected_balance
        assert nos.predictable_validators == 1
        assert nos.predictable_balance == expected_balance
        assert nos.total_stake == expected_balance


@pytest.mark.unit
class TestNextAndIterFull:
    def test_next__returns_validator_and_decrements_balance(self, iterator):
        """__next__ returns the highest-priority validator and updates exit balance."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm)
        gid = (sm.id, no.id)
        weight = float(10 * 10000)
        ms = StakingModuleStats(
            staking_module=sm,
            predictable_balance=Gwei(32 * 10**9),
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator))

        nos = NodeOperatorStats(
            node_operator=no,
            module_stats=ms,
            predictable_validators=1,
            predictable_balance=Gwei(32 * 10**9),
            total_stake=Gwei(32 * 10**9),
            weight=weight,
        )

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.exitable_validators = {gid: [validator]}
        iterator.total_lido_predictable_balance = Gwei(32 * 10**9)
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        step = iterator.__next__()

        assert step.gid == gid
        assert step.validator is validator
        assert step.amount == FWR_AMOUNT

    def test_next__exceeds_limit__raises_stop_iteration(self, iterator):
        """__next__ raises StopIteration when exit limit is exceeded."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm)
        gid = (sm.id, no.id)
        weight = float(10 * 10000)
        ms = StakingModuleStats(
            staking_module=sm,
            predictable_balance=Gwei(32 * 10**9),
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator))

        nos = NodeOperatorStats(
            node_operator=no,
            module_stats=ms,
            predictable_validators=1,
            predictable_balance=Gwei(32 * 10**9),
            total_stake=Gwei(32 * 10**9),
            weight=weight,
        )

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.exitable_validators = {gid: [validator]}
        iterator.total_lido_predictable_balance = Gwei(32 * 10**9)
        iterator.exit_limit_in_gwei = Gwei(0)  # limit already at 0, any exit exceeds it

        with pytest.raises(StopIteration):
            iterator.__next__()

    def test_next__empty_exitable_validators__raises_stop_iteration(self, iterator):
        """__next__ raises StopIteration when no NO has exitable validators."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm)
        gid = (sm.id, no.id)
        weight = float(10 * 10000)
        ms = StakingModuleStats(staking_module=sm)
        nos = NodeOperatorStats(node_operator=no, module_stats=ms, weight=weight)

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.exitable_validators = {gid: []}
        iterator.total_lido_predictable_balance = Gwei(0)
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        with pytest.raises(StopIteration):
            iterator.__next__()

    def test_next__high_priority_no_empty_list__skips_and_selects_populated_no(self, iterator):
        """A high-priority NO with predictable balance/count but no exitable validator must be
        skipped, and the next populated NO selected, without an IndexError."""
        sm = make_staking_module(1)
        no_empty = make_node_operator(1, sm, total_dep=3, target=0, limit_mode=NodeOperatorLimitMode.FORCE)
        no_populated = make_node_operator(2, sm)
        gid_empty = (sm.id, no_empty.id)
        gid_populated = (sm.id, no_populated.id)
        weight = float(10 * 10000)
        ms = StakingModuleStats(
            staking_module=sm,
            predictable_balance=Gwei(128 * 10**9),
        )
        nos_empty = NodeOperatorStats(
            node_operator=no_empty,
            module_stats=ms,
            predictable_validators=3,
            force_exit_to=0,
            predictable_balance=Gwei(96 * 10**9),
            total_stake=Gwei(96 * 10**9),
            weight=weight,
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator))
        nos_populated = NodeOperatorStats(
            node_operator=no_populated,
            module_stats=ms,
            predictable_validators=1,
            predictable_balance=Gwei(32 * 10**9),
            total_stake=Gwei(32 * 10**9),
            weight=weight,
        )

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid_empty: nos_empty, gid_populated: nos_populated}
        iterator.exitable_validators = {gid_empty: [], gid_populated: [validator]}
        iterator.total_lido_predictable_balance = Gwei(128 * 10**9)
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        step = iterator.__next__()

        assert step.gid == gid_populated, "The populated operator must be selected"
        assert step.validator is validator, "The populated operator's validator must be returned"

    def test_iter__initializes_all_state(self, iterator):
        """__iter__ prepares all state and returns self."""
        iterator._reset_iterator_data = Mock()
        iterator._prepare_data_structure = Mock()
        iterator._calculate_lido_stats = Mock()
        iterator._get_report_limits = Mock()

        result = iter(iterator)

        assert result is iterator
        iterator._reset_iterator_data.assert_called_once()
        iterator._prepare_data_structure.assert_called_once()
        iterator._calculate_lido_stats.assert_called_once()
        iterator._get_report_limits.assert_called_once()

    @staticmethod
    def _make_ext_data(sm_id, no_id):
        return bytes([0, sm_id]) + no_id.to_bytes(8, byteorder='big')

    def test_full_iteration__mixed_weight_groups_and_ungrouped_nos__ejects_all_via_full_pipeline(self, iterator):
        sm_v1 = make_staking_module(1, name=CURATED_V1_MODULE_NAME)
        sm_v1.staking_module_address = "0x" + "1" * 40
        sm_v2 = make_staking_module(2, name=CURATED_V2_MODULE_NAME)
        sm_v2.staking_module_address = "0x" + "2" * 40

        ext1 = make_node_operator(1, sm_v1)
        ext2 = make_node_operator(2, sm_v1)
        ext3 = make_node_operator(3, sm_v1)
        ext4 = make_node_operator(4, sm_v1)  # ungrouped
        int1 = make_node_operator(1, sm_v2)
        int2 = make_node_operator(2, sm_v2)
        int3 = make_node_operator(3, sm_v2)
        int4 = make_node_operator(4, sm_v2)
        int5 = make_node_operator(5, sm_v2)  # ungrouped

        gids = {
            'ext1': (sm_v1.id, ext1.id),
            'ext2': (sm_v1.id, ext2.id),
            'ext3': (sm_v1.id, ext3.id),
            'ext4': (sm_v1.id, ext4.id),
            'int1': (sm_v2.id, int1.id),
            'int2': (sm_v2.id, int2.id),
            'int3': (sm_v2.id, int3.id),
            'int4': (sm_v2.id, int4.id),
            'int5': (sm_v2.id, int5.id),
        }
        balances_eth = {
            'ext1': 30,
            'ext2': 20,
            'ext3': 28,
            'ext4': 18,
            'int1': 25,
            'int2': 15,
            'int3': 22,
            'int4': 12,
            'int5': 27,
        }
        validators = {
            name: LidoValidatorFactory.build_with_activation_epoch_bound(
                selectable_bound(iterator), balance=Gwei(balances_eth[name] * 10**9)
            )
            for name in gids
        }

        iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm_v1, sm_v2])
        iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(
            return_value={
                sm_v1.id: [ext1, ext2, ext3, ext4],
                sm_v2.id: [int1, int2, int3, int4, int5],
            }
        )
        iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
            return_value={gids[name]: [validators[name]] for name in gids}
        )
        iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
        iterator.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
            return_value=make_report_limits(max_balance_exit_requested_per_report_in_eth=100_000)
        )

        group_a = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=int1.id, share=5_000),
                SubNodeOperator(node_operator_id=int2.id, share=5_000),
            ],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, ext1.id)),
                ExternalOperator(data=self._make_ext_data(sm_v1.id, ext2.id)),
            ],
        )
        group_b = OperatorGroupFactory.build(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=int3.id, share=4_000),
                SubNodeOperator(node_operator_id=int4.id, share=6_000),
            ],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, ext3.id)),
            ],
        )
        # ext4 / int5 are intentionally not referenced in any group -> stay ungrouped.

        mock_cm_v1_contract = Mock()
        mock_cm_v1_contract.get_type.return_value = CURATED_V1_TYPE

        mock_cm_v2_contract = Mock()
        mock_cm_v2_contract.get_type.return_value = CURATED_V2_TYPE
        mock_cm_v2_contract.get_node_operator_deposit_info_to_update_count.return_value = 0
        # Order must match no_ids order = insertion order of sm_v2's node operators: int1..int5
        mock_cm_v2_contract.get_operator_weights.return_value = [0.0, 0.0, 4.0, 6.0, 3.0]
        meta_registry_address = "0x" + "9" * 40
        mock_cm_v2_contract.get_meta_registry_address.return_value = meta_registry_address

        mock_meta_registry = Mock()
        mock_meta_registry.get_all_groups.return_value = [group_a, group_b]

        contracts_by_addr = {
            sm_v1.staking_module_address: mock_cm_v1_contract,
            sm_v2.staking_module_address: mock_cm_v2_contract,
            meta_registry_address: mock_meta_registry,
        }
        iterator.w3.eth.contract = Mock(side_effect=lambda **kw: contracts_by_addr[kw['address']])

        iterator._prepare_data_structure()
        iterator._calculate_lido_stats()
        iterator._get_report_limits()

        nos_stats = iterator.node_operators_stats
        ETH = 10**9

        # Grouped NOs got linked to their respective group...
        assert nos_stats[gids['int1']].internal_operator_group is group_a
        assert nos_stats[gids['int2']].internal_operator_group is group_a
        assert nos_stats[gids['int3']].internal_operator_group is group_b
        assert nos_stats[gids['int4']].internal_operator_group is group_b
        assert nos_stats[gids['ext1']].external_operator_group is group_a
        assert nos_stats[gids['ext2']].external_operator_group is group_a
        assert nos_stats[gids['ext3']].external_operator_group is group_b
        # ...while ungrouped NOs stayed ungrouped.
        assert nos_stats[gids['int5']].internal_operator_group is None
        assert nos_stats[gids['ext4']].external_operator_group is None

        # Group A (zero internal_weight): external_balance (30+20=50) split by share between int1/int2.
        assert nos_stats[gids['int1']].total_stake == 25 * ETH + 50 * ETH / 2
        assert nos_stats[gids['int2']].total_stake == 15 * ETH + 50 * ETH / 2
        # Group B (internal_weight=10): external_balance (28) split by weight 4/10, 6/10.
        assert nos_stats[gids['int3']].total_stake == 22 * ETH + 28 * ETH * 4.0 / 10.0
        assert nos_stats[gids['int4']].total_stake == 12 * ETH + 28 * ETH * 6.0 / 10.0
        # CMv1 operators keep their own stake (externalStake = 0 outside CMv2), but take the group's weight.
        assert nos_stats[gids['ext1']].total_stake == 30 * ETH
        assert nos_stats[gids['ext2']].total_stake == 20 * ETH
        assert nos_stats[gids['ext3']].total_stake == 28 * ETH
        assert (nos_stats[gids['ext1']].weight, nos_stats[gids['ext3']].weight) == (0.0, 10.0)
        # Ungrouped NOs: own predictable balance only.
        assert nos_stats[gids['int5']].total_stake == 27 * ETH
        assert nos_stats[gids['ext4']].total_stake == 18 * ETH

        # --- Now drain the iterator for real and verify ejection completeness/module attribution ---
        ejected: list[WithdrawalStep] = []
        for _i in range(8):
            ejected.append(next(iterator))

        # Hand-computed: the module share-rate predicate alternates the modules by predictable balance
        # (v2 101 > v1 96 at the start), and the target-stake deviation picks the operator inside each.
        # Exits of ext1/ext3 lower their group's CMv2 external share; CMv2 exits never touch CMv1.
        assert [name for step in ejected for name, gid in gids.items() if gid == step.gid] == [
            'int1',  # v2: deviation +50 (target 0, weight 0)
            'ext1',  # v1: +30 (weight 0); int1/int2 lose 15 ETH of external share each
            'int2',  # v2: +25; int1 has no validator left
            'ext3',  # v1: ~+28 beats ext2 +20; int3/int4 lose 11.2/16.8 ETH
            'int5',  # v2: +8.3 (stake 81 over weights 4/6/3); int3 -2.9, int4 -25.4
            'ext2',  # v1: +20; ext4 below its target
            'int3',  # v2: +11.5
            'ext4',  # v1: the only validator left there
        ]
        ejected_module_counts = Counter(step.gid[0] for step in ejected)
        assert ejected_module_counts[sm_v1.id] == 4
        assert ejected_module_counts[sm_v2.id] == 4

        assert nos_stats[gids['int5']].total_stake == 0 * ETH
        assert nos_stats[gids['ext4']].total_stake == 0 * ETH
        assert nos_stats[gids['int4']].total_stake == 12 * ETH
        assert iterator.module_stats[gids['int4'][0]].predictable_balance == 12 * ETH
        assert iterator.module_stats[gids['ext1'][0]].predictable_balance == 0 * ETH


@pytest.mark.unit
class TestGetRemainingForcedEdgeCases:
    def test_limit_hit_during_forced__returns_partial_list(self, iterator):
        """When exit limit is hit mid-run, only validators collected before the limit are returned."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm, total_dep=3, target=0, limit_mode=NodeOperatorLimitMode.FORCE)
        gid = (sm.id, no.id)
        ms = StakingModuleStats(staking_module=sm, predictable_balance=Gwei(96 * 10**9))
        validators = [
            LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator)) for _ in range(3)
        ]
        nos = NodeOperatorStats(
            node_operator=no,
            module_stats=ms,
            predictable_validators=3,
            predictable_balance=Gwei(96 * 10**9),
            total_stake=Gwei(96 * 10**9),
            force_exit_to=0,
        )

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.exitable_validators = {gid: list(validators)}
        iterator.total_lido_predictable_balance = Gwei(96 * 10**9)
        # Limit = exactly one validator's max effective balance (32 ETH).
        # First validator: cumulative = 32e9, 32e9 > 32e9 is False → added to result.
        # Second validator: cumulative = 64e9, 64e9 > 32e9 is True → return with 1 item.
        iterator.exit_limit_in_gwei = MIN_ACTIVATION_BALANCE

        result = iterator.allocate_forced_exits()

        assert len(result) == 1, "Only the first validator fits within the limit"
        assert result[0].gid == gid

    def test_no_exitable_validators__for_else_breaks(self, iterator):
        """When all NOs have forced exits needed but no exitable validators, loop exits via else:break."""
        sm = make_staking_module(1)
        # force_exit_to=0 but predictable_validators=3 → force_predicate=3
        no = make_node_operator(1, sm, total_dep=3, target=0, limit_mode=NodeOperatorLimitMode.FORCE)
        gid = (sm.id, no.id)
        ms = StakingModuleStats(staking_module=sm)
        nos = NodeOperatorStats(
            node_operator=no,
            module_stats=ms,
            predictable_validators=3,
            force_exit_to=0,
        )

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.exitable_validators = {gid: []}  # No validators left to eject
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        result = iterator.allocate_forced_exits()

        assert result == [], "Empty list when no validators are available despite forced exit need"

    def test_allocate_forced_exits__high_priority_no_empty_list__ejects_from_populated_no(self, iterator):
        """A forced NO with an empty exitable list must be skipped without an IndexError, while the
        next forced NO that still has a validator is ejected."""
        sm = make_staking_module(1)
        no_empty = make_node_operator(1, sm, total_dep=3, target=0, limit_mode=NodeOperatorLimitMode.FORCE)
        no_populated = make_node_operator(2, sm, total_dep=1, target=0, limit_mode=NodeOperatorLimitMode.FORCE)
        gid_empty = (sm.id, no_empty.id)
        gid_populated = (sm.id, no_populated.id)
        ms = StakingModuleStats(staking_module=sm)
        nos_empty = NodeOperatorStats(
            node_operator=no_empty,
            module_stats=ms,
            predictable_validators=3,
            force_exit_to=0,
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(selectable_bound(iterator))
        nos_populated = NodeOperatorStats(
            node_operator=no_populated,
            module_stats=ms,
            predictable_validators=1,
            force_exit_to=0,
        )

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid_empty: nos_empty, gid_populated: nos_populated}
        iterator.exitable_validators = {gid_empty: [], gid_populated: [validator]}
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        result = iterator.allocate_forced_exits()

        assert len(result) == 1, "Only the populated operator yields a forced validator"
        assert result[0].gid == gid_populated
        assert result[0].validator is validator


ETH = 10**9
COMPOUNDING_WC = '0x02' + '00' * 31
ETH1_WC = '0x01' + '00' * 31


def make_validator(index: int, balance_eth: float, wc: str = COMPOUNDING_WC, activation_epoch: int = 0):
    return LidoValidatorFactory.build(
        index=index,
        balance=Gwei(int(balance_eth * ETH)),
        validator=ValidatorStateFactory.build(
            withdrawal_credentials=wc,
            effective_balance=MIN_ACTIVATION_BALANCE,
            activation_epoch=EpochNumber(activation_epoch),
            exit_epoch=FAR_FUTURE_EPOCH,
        ),
    )


def setup_single_operator(iterator, validators, *, partial_allowed=True, wc_type=2, force_exit_to=None):
    """One module with one node operator, so the ranking never decides the outcome."""
    sm = make_staking_module(1, wc_type=wc_type)
    no = make_node_operator(1, sm)
    gid = (sm.id, no.id)
    total = Gwei(sum(get_predictable_inbound_balance(v) for v in validators))
    ms = StakingModuleStats(
        staking_module=sm,
        partial_withdrawals_allowed=partial_allowed,
        predictable_balance=total,
    )
    nos = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=len(validators),
        predictable_balance=total,
        total_stake=total,
        weight=1.0,
        force_exit_to=force_exit_to,
    )
    iterator.module_stats = {sm.id: ms}
    iterator.node_operators_stats = {gid: nos}
    iterator.exitable_validators = {gid: sorted(validators, key=lambda v: v.index)}
    iterator.total_lido_predictable_balance = total
    return gid


@pytest.mark.unit
class TestPwrFwrSelection:
    def test_next__eligible_compounding_validator__takes_one_chunk_pwr(self, iterator):
        validator = make_validator(1, 100)
        gid = setup_single_operator(iterator, [validator])

        step = next(iterator)

        assert step.gid == gid
        assert step.validator is validator
        assert step.amount == Gwei(32 * ETH)
        assert step.inbound == Gwei(32 * ETH)
        assert [(r.key_index, r.amount) for r in iterator.get_requests()] == [(validator.lido_id.index, 32 * ETH)]

    def test_next__in_flight_pwr__reduces_amount(self, iterator):
        validator = make_validator(1, 50)
        setup_single_operator(iterator, [validator])
        iterator.in_flight = InFlightWithdrawals(pwr_amounts={validator.index: Gwei(10 * ETH)})

        step = next(iterator)

        # 50 ETH balance - 10 ETH in flight - 32 ETH MIN_ACTIVATION_BALANCE
        assert step.amount == Gwei(8 * ETH)

    @pytest.mark.parametrize(
        ("balance_eth", "expected_amount"),
        [
            pytest.param(33, Gwei(1 * ETH), id="33_eth__pwr"),
            pytest.param(32.9, FWR_AMOUNT, id="below_33_eth__fwr"),
        ],
    )
    def test_next__pwr_eligibility_threshold__is_33_eth(self, iterator, balance_eth, expected_amount):
        setup_single_operator(iterator, [make_validator(1, balance_eth)])

        assert next(iterator).amount == expected_amount

    def test_next__module_without_partial_withdrawals__fwr_lowest_index(self, iterator):
        low, high = make_validator(3, 100), make_validator(7, 100)
        setup_single_operator(iterator, [high, low], partial_allowed=False)

        step = next(iterator)

        assert step.amount == FWR_AMOUNT
        assert step.validator is low

    def test_next__eth1_validator_in_partial_module__fwr(self, iterator):
        validator = make_validator(1, 100, wc=ETH1_WC)
        setup_single_operator(iterator, [validator], wc_type=1)

        assert next(iterator).amount == FWR_AMOUNT

    def test_next__forced_operator__fwr_even_when_pwr_eligible(self, iterator):
        validator = make_validator(1, 100)
        setup_single_operator(iterator, [validator], force_exit_to=0)

        step = next(iterator)

        assert step.amount == FWR_AMOUNT
        assert step.validator is validator

    def test_next__smallest_eligible_validator__preferred(self, iterator):
        big, small = make_validator(1, 200), make_validator(2, 50)
        setup_single_operator(iterator, [big, small])

        step = next(iterator)

        assert step.validator is small
        assert step.amount == Gwei(18 * ETH)

    def test_next__validator_already_in_report__preferred_over_smaller(self, iterator):
        big, small = make_validator(1, 200), make_validator(2, 50)
        gid = setup_single_operator(iterator, [big, small])
        iterator._allocate(gid, big, Gwei(10 * ETH))

        step = next(iterator)

        assert step.validator is big
        assert [(r.key_index, r.amount) for r in iterator.get_requests()] == [(big.lido_id.index, 42 * ETH)]

    def test_next__balances_above_max_pwr_headroom__smallest_balance_preferred(self, iterator):
        # Both validators can give the full MAX_PWR_AMOUNT, so only the balance tells them apart.
        larger, smaller = make_validator(1, 2049.5), make_validator(2, 2048.4)
        setup_single_operator(iterator, [larger, smaller])

        step = next(iterator)

        assert step.validator is smaller
        assert step.amount == Gwei(32 * ETH)

    def test_next__in_flight_pwr__ranks_by_balance_after_it(self, iterator):
        # 100 ETH with 60 ETH already requested has 40 ETH left, less than the 50 ETH validator.
        drained, plain = make_validator(1, 100), make_validator(2, 50)
        setup_single_operator(iterator, [drained, plain])
        iterator.in_flight = InFlightWithdrawals(pwr_amounts={drained.index: Gwei(60 * ETH)})

        step = next(iterator)

        assert step.validator is drained
        assert step.amount == Gwei(8 * ETH)


@pytest.mark.unit
class TestReportRecords:
    def test_steps_on_one_validator__merge_into_one_pwr__then_fwr_replaces_it(self, iterator):
        validator = make_validator(1, 100)
        setup_single_operator(iterator, [validator])

        steps = [next(iterator) for _ in range(4)]

        # 32 + 32 + 4 ETH of headroom above 32 ETH, then no PWR headroom is left.
        assert [s.amount for s in steps] == [Gwei(32 * ETH), Gwei(32 * ETH), Gwei(4 * ETH), FWR_AMOUNT]
        # The FWR counts the balance minus the PWRs it replaces.
        assert steps[3].inbound == get_predictable_inbound_balance(validator) - Gwei(68 * ETH)
        assert [(r.key_index, r.amount) for r in iterator.get_requests()] == [(validator.lido_id.index, FWR_AMOUNT)]

    def test_pwr__capped_at_max_pwr_amount(self, iterator):
        validator = make_validator(1, 3000)
        validator.validator.effective_balance = Gwei(2048 * ETH)
        setup_single_operator(iterator, [validator])
        iterator.chunk = Gwei(5000 * ETH)

        first, second = next(iterator), next(iterator)

        assert first.amount == MAX_PWR_AMOUNT
        assert second.amount == FWR_AMOUNT, "No PWR headroom left under MAX_PWR_AMOUNT"

    def test_fwr_after_in_report_pwr__replaces_it_in_place(self, iterator):
        x, y = make_validator(1, 100), make_validator(2, 100)
        gid = setup_single_operator(iterator, [x, y])
        iterator._allocate(gid, x, Gwei(10 * ETH))
        iterator._allocate(gid, y, Gwei(5 * ETH))

        step = iterator._allocate(gid, x, FWR_AMOUNT)

        assert step is not None
        assert step.inbound == get_predictable_inbound_balance(x) - Gwei(10 * ETH)
        assert [(r.key_index, r.amount) for r in iterator.get_requests()] == [
            (x.lido_id.index, FWR_AMOUNT),
            (y.lido_id.index, Gwei(5 * ETH)),
        ], "The FWR keeps the PWR's position and the report keeps one record per validator"
        assert iterator._pwr_total == Gwei(5 * ETH)
        assert iterator._fwr_weight == Gwei(2048 * ETH)

    def test_record_cap__counts_records_not_steps(self, iterator):
        first, second = make_validator(1, 200), make_validator(2, 300)
        setup_single_operator(iterator, [first, second])
        iterator.max_exit_requests_per_report = 1

        steps = [next(iterator) for _ in range(3)]

        assert {s.validator.index for s in steps} == {first.index}
        assert len(iterator.get_requests()) == 1


@pytest.mark.unit
class TestInFlightWithdrawals:
    def test_next__in_flight_pwr__never_fwr(self, iterator):
        blocked, free = make_validator(1, 32), make_validator(2, 32)
        setup_single_operator(iterator, [blocked, free], partial_allowed=False)
        iterator.in_flight = InFlightWithdrawals(pwr_amounts={blocked.index: Gwei(1 * ETH)})

        assert next(iterator).validator is free

    def test_next__only_validator_has_in_flight_pwr__stops(self, iterator):
        blocked = make_validator(1, 32)
        setup_single_operator(iterator, [blocked], partial_allowed=False)
        iterator.in_flight = InFlightWithdrawals(pwr_amounts={blocked.index: Gwei(1 * ETH)})

        with pytest.raises(StopIteration):
            next(iterator)

    def test_is_validator_exitable__in_flight_fwr__not_exitable(self, iterator):
        validator = make_validator(1, 32)
        iterator.in_flight = InFlightWithdrawals(fwr_validators=frozenset({validator.index}))

        assert iterator._is_validator_exitable(validator) is False


@pytest.mark.unit
class TestShardCommitteePeriod:
    def test_recently_activated_validator__exitable_but_not_selected(self, iterator):
        fresh = make_validator(1, 100, activation_epoch=iterator.blockstamp.ref_epoch - SHARD_COMMITTEE_PERIOD + 1)
        setup_single_operator(iterator, [fresh])

        # Still counted in stake accounting...
        assert iterator._is_validator_exitable(fresh) is True
        # ...but never selected for a withdrawal.
        with pytest.raises(StopIteration):
            next(iterator)

    def test_validator_at_shard_committee_period_boundary__selected(self, iterator):
        ready = make_validator(1, 100, activation_epoch=iterator.blockstamp.ref_epoch - SHARD_COMMITTEE_PERIOD)
        setup_single_operator(iterator, [ready])

        assert next(iterator).validator is ready


@pytest.mark.unit
class TestReportExitLimit:
    @pytest.mark.parametrize(
        ("pwr_total", "fwr_weight", "expected"),
        [
            pytest.param(Gwei(1), Gwei(0), Gwei(1 * ETH), id="dust_rounds_up"),
            pytest.param(Gwei(32 * ETH + 1), Gwei(0), Gwei(33 * ETH), id="above_whole_eth_rounds_up"),
            pytest.param(Gwei(32 * ETH), Gwei(2048 * ETH), Gwei(2080 * ETH), id="pwr_plus_fwr"),
        ],
    )
    def test_get_exit_weight__pwr_rounded_up_to_whole_eth(self, pwr_total, fwr_weight, expected):
        assert ValidatorExitIterator._get_exit_weight(pwr_total, fwr_weight) == expected

    def test_pwr_limit__rounded_weight_fits__next_chunk_stops(self, iterator):
        setup_single_operator(iterator, [make_validator(1, 200)])
        iterator.chunk = Gwei(int(32.5 * ETH))
        iterator.exit_limit_in_gwei = Gwei(33 * ETH)

        assert next(iterator).amount == Gwei(int(32.5 * ETH))
        with pytest.raises(StopIteration):
            next(iterator)

    @pytest.mark.parametrize(
        ("wc_type", "fits"),
        [pytest.param(1, True, id="0x01_module__32_eth_weight"), pytest.param(2, False, id="0x02_module__2048_eth")],
    )
    def test_fwr_weight__by_module_wc_type(self, iterator, wc_type, fits):
        setup_single_operator(iterator, [make_validator(1, 32)], partial_allowed=False, wc_type=wc_type)
        iterator.exit_limit_in_gwei = Gwei(100 * ETH)

        if fits:
            assert next(iterator).amount == FWR_AMOUNT
            assert iterator._fwr_weight == Gwei(32 * ETH)
        else:
            with pytest.raises(StopIteration):
                next(iterator)
            assert iterator.get_requests() == []


CMV2_ID = StakingModuleId(2)


def setup_cmv2_operators(iterator, operators, *, partial_allowed=True, first_activation_epoch=0):
    """
    CMv2 operators given as {no_id: (validators, weight)}. Each operator's stake is the sum of its
    validator balances, with no external stake and no pending deposits.
    """
    sm = make_staking_module(CMV2_ID, wc_type=2)
    total = Gwei(sum(int(v.balance) for validators, _ in operators.values() for v in validators))
    ms = StakingModuleStats(
        staking_module=sm,
        partial_withdrawals_allowed=partial_allowed,
        is_cm_v2=True,
        predictable_balance=total,
    )
    iterator.module_stats = {sm.id: ms}
    iterator.node_operators_stats = {}
    iterator.exitable_validators = {}
    iterator.first_activation_epoch = {}
    for no_id, (validators, weight) in operators.items():
        gid = (sm.id, NodeOperatorId(no_id))
        stake = Gwei(sum(int(v.balance) for v in validators))
        iterator.node_operators_stats[gid] = NodeOperatorStats(
            node_operator=make_node_operator(no_id, sm),
            module_stats=ms,
            predictable_validators=len(validators),
            predictable_balance=stake,
            total_stake=stake,
            weight=float(weight),
        )
        iterator.exitable_validators[gid] = sorted(validators, key=lambda v: v.index)
        iterator.first_activation_epoch[gid] = EpochNumber(first_activation_epoch)
    iterator.cm_v2_id = sm.id
    iterator.total_lido_predictable_balance = total


def enable_rebalancing(iterator, *, rate_limit_eth=10_000, operator_bp=1_000, module_bp=100_000, grace_epochs=0):
    """module_bp=100_000 keeps the module-level trigger off: excess can never exceed 10x the module stake."""
    daemon_config = iterator.w3.lido_contracts.oracle_daemon_config
    daemon_config.active_rebalancing_enabled = Mock(return_value=True)
    daemon_config.active_rebalancing_rate_limit_eth = Mock(return_value=rate_limit_eth)
    daemon_config.active_rebalancing_operator_excess_bp = Mock(return_value=operator_bp)
    daemon_config.active_rebalancing_module_excess_bp = Mock(return_value=module_bp)
    daemon_config.active_rebalancing_grace_period_epochs = Mock(return_value=grace_epochs)


def gid_of(no_id):
    return (CMV2_ID, NodeOperatorId(no_id))


@pytest.mark.unit
class TestActiveRebalancing:
    def test_allocate_active_rebalancing__disabled__no_requests_and_no_other_keys_read(self, iterator):
        # Arrange
        setup_cmv2_operators(iterator, {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1)})
        enable_rebalancing(iterator)
        daemon_config = iterator.w3.lido_contracts.oracle_daemon_config
        daemon_config.active_rebalancing_enabled = Mock(return_value=False)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert steps == []
        assert iterator.get_requests() == []
        daemon_config.active_rebalancing_rate_limit_eth.assert_not_called()

    def test_allocate_active_rebalancing__operator_trigger__pwr_until_within_threshold(self, iterator):
        # Arrange: equal weights, stakes 400/100/100, target 200 each, operator threshold 10%.
        # After k chunks of 32 ETH the trigger is 3 * (400 - 32k) > 1.1 * (600 - 32k), true for k <= 8.
        validator = make_validator(1, 400)
        setup_cmv2_operators(
            iterator,
            {1: ([validator], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        enable_rebalancing(iterator, operator_bp=1_000)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert len(steps) == 9
        assert {step.gid for step in steps} == {gid_of(1)}
        assert [(r.key_index, r.amount) for r in iterator.get_requests()] == [(validator.lido_id.index, 288 * ETH)]

    def test_allocate_active_rebalancing__module_trigger__pwr_until_within_threshold(self, iterator):
        # Arrange: operator trigger off, module threshold 20%.
        # Sum of excess (600 - 64k) / 3 > 0.2 * (600 - 32k) holds for k <= 5.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        enable_rebalancing(iterator, operator_bp=1_000_000, module_bp=2_000)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert len(steps) == 6
        assert sum(step.amount for step in steps) == 192 * ETH

    def test_allocate_active_rebalancing__small_deviation__dormant(self, iterator):
        # Arrange: 210/200/200, target 203.33, excess 3.3% of target and 1.1% of the module.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 210)], 1), 2: ([make_validator(2, 200)], 1), 3: ([make_validator(3, 200)], 1)},
        )
        enable_rebalancing(iterator, operator_bp=1_000, module_bp=2_000)

        # Act / Assert
        assert iterator.allocate_active_rebalancing() == []

    def test_allocate_active_rebalancing__rate_limit__stops_before_exceeding(self, iterator):
        # Arrange: three 32 ETH chunks fit into 100 ETH, the fourth does not.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        enable_rebalancing(iterator, rate_limit_eth=100)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert [step.amount for step in steps] == [Gwei(32 * ETH)] * 3

    def test_allocate_active_rebalancing__fwr__weighs_validator_balance_against_rate_limit(self, iterator):
        # Arrange: no PWRs in the module, so FWRs from the lowest index. One 200 ETH FWR fits into 399 ETH,
        # a second one does not, although the operator is still above its target.
        low, high = make_validator(3, 200), make_validator(5, 200)
        setup_cmv2_operators(
            iterator,
            {1: ([high, low], 1), 2: ([make_validator(6, 100)], 1), 3: ([make_validator(7, 100)], 1)},
            partial_allowed=False,
        )
        enable_rebalancing(iterator, rate_limit_eth=399)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert [(step.validator, step.amount) for step in steps] == [(low, FWR_AMOUNT)]

    def test_allocate_active_rebalancing__shared_report_limit__stops_phase(self, iterator):
        # Arrange: the shared per-report limit leaves room for two 32 ETH chunks.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        enable_rebalancing(iterator)
        iterator.exit_limit_in_gwei = Gwei(64 * ETH)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert len(steps) == 2

    def test_allocate_active_rebalancing__in_flight_pwr__counted_out_of_current_stake(self, iterator):
        # Arrange: 400 ETH minus 300 ETH already in flight leaves 100/100/100.
        validator = make_validator(1, 400)
        setup_cmv2_operators(
            iterator,
            {1: ([validator], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        iterator.in_flight = InFlightWithdrawals(pwr_amounts={validator.index: Gwei(300 * ETH)})
        enable_rebalancing(iterator)

        # Act / Assert
        assert iterator.allocate_active_rebalancing() == []

    def test_allocate_active_rebalancing__operator_in_grace_period__excluded(self, iterator):
        # Arrange: the 400 ETH operator activated 10 epochs ago, inside a 100-epoch grace period.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        iterator.first_activation_epoch[gid_of(1)] = EpochNumber(iterator.blockstamp.ref_epoch - 10)
        enable_rebalancing(iterator, grace_epochs=100)

        # Act / Assert
        assert iterator.allocate_active_rebalancing() == []

    def test_allocate_active_rebalancing__grace_period_elapsed__operator_targeted(self, iterator):
        # Arrange: exactly the grace period since the first activation.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        iterator.first_activation_epoch[gid_of(1)] = EpochNumber(iterator.blockstamp.ref_epoch - 100)
        enable_rebalancing(iterator, grace_epochs=100)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert steps and {step.gid for step in steps} == {gid_of(1)}

    def test_allocate_active_rebalancing__operator_without_activation__excluded(self, iterator):
        # Arrange: an operator with no activated validator is in the grace period by definition.
        setup_cmv2_operators(
            iterator,
            {1: ([make_validator(1, 400)], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        del iterator.first_activation_epoch[gid_of(1)]
        enable_rebalancing(iterator)

        # Act / Assert
        assert iterator.allocate_active_rebalancing() == []

    def test_allocate_active_rebalancing__weights__target_follows_weight(self, iterator):
        # Arrange: weights 3/1, stakes 300/100 are exactly on target; 200/200 puts operator 2 100 ETH above.
        setup_cmv2_operators(iterator, {1: ([make_validator(1, 200)], 3), 2: ([make_validator(2, 200)], 1)})
        enable_rebalancing(iterator)

        # Act
        steps = iterator.allocate_active_rebalancing()

        # Assert
        assert steps and {step.gid for step in steps} == {gid_of(2)}

    def test_allocate_active_rebalancing__non_cmv2_operator__never_targeted(self, iterator):
        # Arrange: a CMv1 operator far above any target is outside Phase 3.
        setup_cmv2_operators(iterator, {1: ([make_validator(1, 100)], 1), 2: ([make_validator(2, 100)], 1)})
        cm_v1 = make_staking_module(1, wc_type=2)
        cm_v1_gid = (cm_v1.id, NodeOperatorId(9))
        iterator.module_stats[cm_v1.id] = StakingModuleStats(staking_module=cm_v1, partial_withdrawals_allowed=True)
        iterator.node_operators_stats[cm_v1_gid] = NodeOperatorStats(
            node_operator=make_node_operator(9, cm_v1),
            module_stats=iterator.module_stats[cm_v1.id],
            total_stake=Gwei(1000 * ETH),
        )
        iterator.exitable_validators[cm_v1_gid] = [make_validator(9, 1000)]
        iterator.first_activation_epoch[cm_v1_gid] = EpochNumber(0)
        enable_rebalancing(iterator)

        # Act / Assert
        assert iterator.allocate_active_rebalancing() == []


@pytest.mark.unit
class TestFirstActivationEpoch:
    def test_prepare_validator_stats__mixed_activations__earliest_activated_epoch(self, iterator):
        # Arrange
        ref_epoch = iterator.blockstamp.ref_epoch
        gid_active, gid_pending = (CMV2_ID, NodeOperatorId(1)), (CMV2_ID, NodeOperatorId(2))
        iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
            return_value={
                gid_active: [
                    make_validator(1, 32, activation_epoch=ref_epoch - 10),
                    make_validator(2, 32, activation_epoch=ref_epoch - 50),
                    make_validator(3, 32, activation_epoch=FAR_FUTURE_EPOCH),
                ],
                gid_pending: [make_validator(4, 32, activation_epoch=FAR_FUTURE_EPOCH)],
            }
        )

        # Act
        iterator._prepare_validator_stats()

        # Assert
        assert iterator.first_activation_epoch == {gid_active: ref_epoch - 50}


@pytest.mark.unit
class TestPhasesShareReportLimit:
    def test_all_phases__one_report_limit__phase_3_gets_what_phases_1_and_2_left(self, iterator):
        # Arrange: CMv2 operators 400/100/100 ETH with equal weights (target 200 each).
        a1 = make_validator(1, 400)
        setup_cmv2_operators(
            iterator,
            {1: ([a1], 1), 2: ([make_validator(2, 100)], 1), 3: ([make_validator(3, 100)], 1)},
        )
        # A 0x01 module operator that must exit both of its validators.
        sm1 = make_staking_module(1, wc_type=1)
        forced = make_node_operator(9, sm1)
        f1, f2 = make_validator(11, 32, wc=ETH1_WC), make_validator(12, 32, wc=ETH1_WC)
        forced_gid = (sm1.id, forced.id)
        ms1 = StakingModuleStats(staking_module=sm1, predictable_balance=Gwei(64 * ETH))
        iterator.module_stats[sm1.id] = ms1
        iterator.node_operators_stats[forced_gid] = NodeOperatorStats(
            node_operator=forced,
            module_stats=ms1,
            predictable_validators=2,
            predictable_balance=Gwei(64 * ETH),
            total_stake=Gwei(64 * ETH),
            force_exit_to=0,
        )
        iterator.exitable_validators[forced_gid] = [f1, f2]
        iterator.first_activation_epoch[forced_gid] = EpochNumber(0)
        iterator.total_lido_predictable_balance = Gwei(iterator.total_lido_predictable_balance + 64 * ETH)
        # FWR of a 0x01 module weighs 32 ETH, a PWR its amount: 160 ETH fits two FWRs and three 32 ETH PWRs.
        iterator.exit_limit_in_gwei = Gwei(160 * ETH)
        enable_rebalancing(iterator, operator_bp=1_000)

        # Act
        phase_1 = next(iterator)
        phase_2 = iterator.allocate_forced_exits()
        phase_3 = iterator.allocate_active_rebalancing()

        # Assert
        assert (phase_1.validator, phase_1.amount) == (f1, FWR_AMOUNT), "a forced operator ranks first in phase 1"
        assert [(s.validator, s.amount) for s in phase_2] == [(f2, FWR_AMOUNT)]
        # The trigger alone would allow 9 chunks; the 96 ETH left under the shared limit allow 3.
        assert [(s.validator, s.amount) for s in phase_3] == [(a1, Gwei(32 * ETH))] * 3
        assert [(r.key_index, r.amount) for r in iterator.get_requests()] == [
            (f1.lido_id.index, FWR_AMOUNT),
            (f2.lido_id.index, FWR_AMOUNT),
            (a1.lido_id.index, 96 * ETH),
        ]
