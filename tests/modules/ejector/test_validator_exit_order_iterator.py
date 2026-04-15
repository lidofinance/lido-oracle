from unittest.mock import Mock

import pytest

from src.constants import FAR_FUTURE_EPOCH
from src.modules.common.types import ChainConfig
from src.services.exit_order_iterator import NodeOperatorStats, StakingModuleStats, ValidatorExitIterator
from src.types import Gwei, NodeOperatorId, StakingModuleId
from src.web3py.extensions.lido_validators import NodeOperator, NodeOperatorLimitMode, StakingModule
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import LidoValidatorFactory, ValidatorStateFactory


@pytest.fixture
def iterator(web3):
    it = ValidatorExitIterator(
        web3,
        ReferenceBlockStampFactory.build(),
        ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=0),
    )
    it.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[])
    it.w3.lido_validators.get_lido_node_operators = Mock(return_value=[])
    it.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={})
    it.w3.lido_validators.get_lido_validators_by_node_operators = Mock(return_value={})
    it.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={})
    it.w3.cc.get_validators_by_indexes = Mock(return_value={})
    it.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits = Mock(
        return_value=Mock(max_balance_exit_requested_per_report_in_eth=100)
    )
    it.w3.eth.contract = Mock()
    it._reset_iterator_data()
    return it


def make_staking_module(sm_id, threshold=10000):
    return StakingModule(
        id=StakingModuleId(sm_id),
        staking_module_address="0x" + "1" * 40,
        staking_module_fee=0,
        treasury_fee=0,
        stake_share_limit=0,
        status=0,
        name="test",
        last_deposit_at=0,
        last_deposit_block=0,
        exited_validators_count=0,
        priority_exit_share_threshold=threshold,
        max_deposits_per_block=0,
        min_deposit_block_distance=0,
        withdrawal_credentials_type=0,
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
def test_get_filter_non_exitable_validators(iterator):
    gid1 = (StakingModuleId(1), NodeOperatorId(1))
    gid2 = (StakingModuleId(1), NodeOperatorId(2))
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid1: [1], gid2: [-1]})
    filt = iterator.get_can_request_exit_predicate(gid1)
    assert not filt(LidoValidatorFactory.build(index=1))
    filt = iterator.get_can_request_exit_predicate(gid2)
    assert filt(LidoValidatorFactory.build(index=1))


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
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch) for _ in range(3)
            ]
        }
    )
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid11: [-1]})
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._setup_cm_data = Mock()  # Skip contract call

    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()

    assert iterator.node_operators_stats[gid11].predictable_validators == 3
    iterator._eject_validator(gid11)
    assert iterator.node_operators_stats[gid11].predictable_validators == 2


@pytest.mark.unit
def test_no_predicate(iterator):
    iterator.total_lido_predictable_balance = Gwei(1000 * 32 * 10**9)
    sm1 = make_staking_module(1, threshold=int(0.15 * 10000))
    sm2 = make_staking_module(2, threshold=int(0.15 * 10000))
    no1 = make_node_operator(1, sm1)
    no2 = make_node_operator(2, sm2)

    ms2 = StakingModuleStats(staking_module=sm2, predictable_balance=Gwei(200 * 32 * 10**9))

    nos2 = NodeOperatorStats(
        node_operator=no2, module_stats=ms2, predictable_validators=2000, force_exit_to=50, soft_exit_to=25
    )

    iterator.exitable_validators = {
        (sm1.id, no1.id): [Mock(index=10, balance=Gwei(32 * 10**9))],
        (sm2.id, no2.id): [Mock(index=20, balance=Gwei(32 * 10**9))],
    }

    # predictable_balance > max_module_predictable_balance:
    # (200 * 32e9) - (0.15 * 1000 * 32e9) = (200 - 150) * 32e9 = 50 * 32e9 = 1600000000000
    res2 = iterator._no_predicate(nos2)
    assert res2[0] == 50 - 2000
    assert res2[1] == 25 - 2000
    assert res2[2] == -(50 * 32 * 10**9)
    assert res2[3] == 0
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

    sorted_s = sorted(nos, key=lambda x: -iterator._no_soft_predicate(x))
    assert [n.node_operator.id for n in sorted_s][:2] == [NodeOperatorId(3), NodeOperatorId(2)]


# @pytest.mark.unit
# def test_max_share_rate_coefficient_predicate(iterator):
#     def make_stats_small(id_val, sm_id, balance):
#         sm = make_staking_module(sm_id)
#         ms = StakingModuleStats(staking_module=sm, predictable_balance=Gwei(balance * 10**9))
#         return NodeOperatorStats(
#             node_operator=make_node_operator(id_val, sm), module_stats=ms, predictable_validators=1
#         )
#
#     nos = [
#         make_stats_small(1, 1, 1000), # 10000 // 1000 = 10
#         make_stats_small(2, 2, 500),  # 10000 // 500 = 20
#         make_stats_small(3, 3, 2000), # 10000 // 2000 = 5
#     ]
#     # Sorting by -predicate (so 20, 10, 5)
#     sorted_nos = sorted(nos, key=lambda x: -iterator._max_share_rate_coefficient_predicate(x))
#     assert sorted_nos[0].node_operator.id == NodeOperatorId(2)
#     assert sorted_nos[1].node_operator.id == NodeOperatorId(1)
#     assert sorted_nos[2].node_operator.id == NodeOperatorId(3)


@pytest.mark.unit
def test_lowest_validators_index_predicate(iterator):
    sm = make_staking_module(1)
    no1 = make_node_operator(1, sm)
    no2 = make_node_operator(2, sm)
    ms = StakingModuleStats(staking_module=sm)
    iterator.exitable_validators = {(sm.id, no1.id): [Mock(index=5)], (sm.id, no2.id): [Mock(index=10)]}
    assert iterator._lowest_validator_index_predicate(NodeOperatorStats(no1, ms)) == 5
    assert iterator._lowest_validator_index_predicate(NodeOperatorStats(no2, ms)) == 10


@pytest.mark.unit
def test_get_remaining_forced_validators(iterator):
    """Forced validators above their force exit target are returned by get_remaining_forced_validators."""
    sm1 = make_staking_module(1)
    no1 = make_node_operator(1, sm1, total_dep=3, target=1, limit_mode=NodeOperatorLimitMode.FORCE)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={
            gid11: [
                LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch) for _ in range(3)
            ]
        }
    )
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid11: [-1]})
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._setup_cm_data = Mock()

    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()

    # These attributes are normally set by __iter__; set them manually for the test
    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)
    iterator.max_current_exit_balance = Gwei(0)

    # force_exit_to=1, predictable_validators=3 → 2 validators should be forcefully ejected
    forced = iterator.get_remaining_forced_validators()
    assert len(forced) == 2, "Expected 2 forced validators (3 validators, target 1)"
    assert all(gid == gid11 for gid, _ in forced)


@pytest.mark.unit
def test_get_remaining_forced_validators_none_needed(iterator):
    """When all validators are at or below their force exit target, returns empty list."""
    sm1 = make_staking_module(1)
    # target=2 > total deposited=1, so no forced exit is needed
    no1 = make_node_operator(1, sm1, total_dep=1, target=2, limit_mode=NodeOperatorLimitMode.FORCE)
    gid11 = (sm1.id, no1.id)

    iterator.w3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[sm1])
    iterator.w3.lido_validators.get_lido_node_operators_by_modules = Mock(return_value={sm1.id: [no1]})
    iterator.w3.lido_validators.get_lido_validators_by_node_operators = Mock(
        return_value={gid11: [LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch)]}
    )
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid11: [-1]})
    iterator.w3.lido_validators.get_pending_lido_validators = Mock(return_value={})
    iterator._setup_cm_data = Mock()

    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()

    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)
    iterator.max_current_exit_balance = Gwei(0)

    forced = iterator.get_remaining_forced_validators()
    assert forced == [], "No forced exits needed when validators are below target"


@pytest.mark.unit
def test_make_exit_predicate_on_exit_validator(iterator):
    """Validators with exit_epoch != FAR_FUTURE_EPOCH are not exitable."""
    gid = (StakingModuleId(1), NodeOperatorId(1))
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid: []})

    filt = iterator.get_can_request_exit_predicate(gid)

    on_exit_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(exit_epoch=100),  # Not FAR_FUTURE_EPOCH
    )
    assert not filt(on_exit_validator), "Validator already on exit should not be exitable"

    active_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
    )
    assert filt(active_validator), "Active validator should be exitable"


@pytest.mark.unit
def test_make_exit_predicate_consolidating_as_source(iterator):
    """Validators with consolidating_as_source set are not exitable."""
    gid = (StakingModuleId(1), NodeOperatorId(1))
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid: []})

    filt = iterator.get_can_request_exit_predicate(gid)

    # Validator being used as a consolidation source should NOT be exitable
    consolidating_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
    )
    consolidating_validator._consolidating_as_source = Mock()  # type: ignore[assignment]

    assert not filt(consolidating_validator), "Validator being consolidated as source should not be exitable"


@pytest.mark.unit
def test_no_weight_predicate(iterator):
    """_no_weight_predicate returns 0 for zero balance, otherwise weight / predictable_balance."""
    sm = make_staking_module(1)
    no = make_node_operator(1, sm)
    ms = StakingModuleStats(staking_module=sm)

    # Zero predictable_balance → return 0
    nos_zero = NodeOperatorStats(node_operator=no, module_stats=ms, predictable_validators=0)
    assert iterator._no_weight_predicate(nos_zero) == 0

    # Non-zero balance → return weight / predictable_balance
    nos_with_balance = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        predictable_balance=Gwei(100 * 10**9),
        weight=2.0,
    )
    expected = 2.0 / (100 * 10**9)
    assert iterator._no_weight_predicate(nos_with_balance) == pytest.approx(expected)


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
