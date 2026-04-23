from unittest.mock import Mock

import pytest

from src.constants import FAR_FUTURE_EPOCH
from src.modules.common.types import ChainConfig
from src.providers.execution.contracts.meta_registry import ExternalOperator, OperatorGroup, SubNodeOperator
from src.services.exit_order_iterator import (
    NodeOperatorAlreadyGroupedError,
    NodeOperatorStats,
    StakingModuleStats,
    ValidatorExitIterator,
)
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
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()  # Skip contract calls
    iterator._calculate_sm_weights = Mock()  # Skip weight calculation

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

    ms2 = StakingModuleStats(
        staking_module=sm2,
        predictable_balance=Gwei(200 * 32 * 10**9),
        total_stake=Gwei(200 * 32 * 10**9),
        total_weight=10.0,
    )

    nos2 = NodeOperatorStats(
        node_operator=no2,
        module_stats=ms2,
        predictable_validators=2000,
        force_exit_to=50,
        soft_exit_to=25,
        predictable_balance=Gwei(200 * 32 * 10**9),
        weight=10.0,
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
def test_get_remaining_forced_validators__force_target_exceeded__returns_excess(iterator):
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
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()
    iterator._calculate_sm_weights = Mock()
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
def test_get_remaining_forced_validators__below_target__returns_empty(iterator):
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
    iterator._finalize_cm_v1_and_cm_v2_stats = Mock()
    iterator._calculate_sm_weights = Mock()
    iterator._prepare_data_structure()
    iterator._calculate_lido_stats()
    # These attributes are normally set by __iter__; set them manually for the test
    iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)
    iterator.max_current_exit_balance = Gwei(0)

    forced = iterator.get_remaining_forced_validators()

    assert forced == [], "No forced exits needed when validators are below target"


@pytest.mark.unit
def test_get_can_request_exit_predicate__validator_on_exit__not_exitable(iterator):
    """Validators with exit_epoch != FAR_FUTURE_EPOCH are not exitable."""
    gid = (StakingModuleId(1), NodeOperatorId(1))
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid: []})

    filt = iterator.get_can_request_exit_predicate(gid)

    on_exit_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(exit_epoch=100),  # Not FAR_FUTURE_EPOCH
    )
    active_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
    )

    assert not filt(on_exit_validator), "Validator already on exit should not be exitable"
    assert filt(active_validator), "Active validator should be exitable"


@pytest.mark.unit
def test_get_can_request_exit_predicate__consolidating_as_source__not_exitable(iterator):
    """Validators with consolidating_as_source set are not exitable."""
    gid = (StakingModuleId(1), NodeOperatorId(1))
    iterator.lvs.get_recently_requested_to_exit_validators_by_node_operator = Mock(return_value={gid: []})
    consolidating_validator = LidoValidatorFactory.build(
        validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
        consolidating_as_source=Mock(),
    )

    filt = iterator.get_can_request_exit_predicate(gid)

    assert not filt(consolidating_validator), "Validator being consolidated as source should not be exitable"


@pytest.mark.unit
def test_no_target_balance_deviation_predicate(iterator):
    """_no_target_balance_deviation_predicate returns target_balance - predictable_balance."""
    sm = make_staking_module(1)
    no = make_node_operator(1, sm)
    ms = StakingModuleStats(staking_module=sm, total_stake=Gwei(1000 * 10**9), total_weight=10.0)

    # Equal to target → deviation is 0
    # target = 1000e9 * 5.0 / 10.0 = 500e9
    nos_at_target = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        predictable_balance=Gwei(500 * 10**9),
        weight=5.0,
    )
    assert iterator._no_target_balance_deviation_predicate(nos_at_target) == 0

    # Below target → positive deviation (higher exit priority)
    nos_below = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        predictable_balance=Gwei(100 * 10**9),
        weight=5.0,
    )
    # target = 500e9, deviation = 500e9 - 100e9 = 400e9
    assert iterator._no_target_balance_deviation_predicate(nos_below) == Gwei(400 * 10**9)

    # Above target → negative deviation (lower exit priority)
    nos_above = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        predictable_balance=Gwei(800 * 10**9),
        weight=5.0,
    )
    # target = 500e9, deviation = 500e9 - 800e9 = -300e9
    assert iterator._no_target_balance_deviation_predicate(nos_above) == Gwei(-300 * 10**9)


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
class TestCalculateSmWeights:
    def test_calculate_sm_weights__multiple_modules__sums_weights_per_module(self, iterator):
        sm1 = make_staking_module(1)
        sm2 = make_staking_module(2)
        ms1 = StakingModuleStats(staking_module=sm1)
        ms2 = StakingModuleStats(staking_module=sm2)
        iterator.module_stats = {sm1.id: ms1, sm2.id: ms2}
        iterator.node_operators_stats = {
            (sm1.id, NodeOperatorId(1)): NodeOperatorStats(
                node_operator=make_node_operator(1, sm1),
                module_stats=ms1,
                weight=3.0,
            ),
            (sm1.id, NodeOperatorId(2)): NodeOperatorStats(
                node_operator=make_node_operator(2, sm1),
                module_stats=ms1,
                weight=7.0,
            ),
            (sm2.id, NodeOperatorId(3)): NodeOperatorStats(
                node_operator=make_node_operator(3, sm2),
                module_stats=ms2,
                weight=5.0,
            ),
        }

        iterator._calculate_sm_weights()

        assert ms1.total_weight == 10.0
        assert ms2.total_weight == 5.0


@pytest.mark.unit
class TestProcessGroup:
    @staticmethod
    def _make_ext_data(sm_id, no_id):
        return bytes([0, sm_id]) + no_id.to_bytes(8, byteorder='big')

    def test_process_group__two_internal_two_external__redistributes_balance_and_weight(self, iterator):
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
            weight=1.0,
        )
        nos_ext2 = NodeOperatorStats(
            node_operator=no_ext2,
            module_stats=ms_v1,
            predictable_balance=Gwei(30 * 10**9),
            weight=2.0,
        )
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            (sm_v2.id, no_int1.id): nos_int1,
            (sm_v2.id, no_int2.id): nos_int2,
            (sm_v1.id, no_ext1.id): nos_ext1,
            (sm_v1.id, no_ext2.id): nos_ext2,
        }
        group = OperatorGroup(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no_int1.id, share=50),
                SubNodeOperator(node_operator_id=no_int2.id, share=50),
            ],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext1.id)),
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext2.id)),
            ],
        )

        iterator._process_group(group, sm_v2.id)

        assert nos_int1.grouped is True
        assert nos_int2.grouped is True
        assert nos_ext1.grouped is True
        assert nos_ext2.grouped is True
        assert ms_v2.total_stake == Gwei(80 * 10**9)
        assert nos_ext1.total_stake == Gwei(150 * 10**9)
        assert nos_ext2.total_stake == Gwei(150 * 10**9)
        assert nos_ext1.weight == 1.0 + 5.0
        assert nos_ext2.weight == 2.0 + 5.0

    def test_process_group__already_grouped_internal__raises_error(self, iterator):
        sm = make_staking_module(1)
        ms = StakingModuleStats(staking_module=sm)
        no1 = make_node_operator(1, sm)
        nos1 = NodeOperatorStats(node_operator=no1, module_stats=ms, grouped=True)
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {(sm.id, no1.id): nos1}
        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=no1.id, share=100)],
            external_operators=[],
        )

        with pytest.raises(NodeOperatorAlreadyGroupedError):
            iterator._process_group(group, sm.id)

    def test_process_group__already_grouped_external__raises_error(self, iterator):
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        no_ext = make_node_operator(5, sm_v1)
        nos_ext = NodeOperatorStats(node_operator=no_ext, module_stats=ms_v1, grouped=True)
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {(sm_v1.id, no_ext.id): nos_ext}
        group = OperatorGroup(
            sub_node_operators=[],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )

        with pytest.raises(NodeOperatorAlreadyGroupedError):
            iterator._process_group(group, sm_v2.id)


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
            total_stake=initial_stake,
        )
        nos = NodeOperatorStats(
            node_operator=no,
            module_stats=ms,
            predictable_validators=2,
            predictable_balance=initial_stake,
            total_stake=initial_stake,
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch)
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.total_lido_predictable_balance = initial_stake
        iterator.exitable_validators = {gid: [validator]}
        from src.utils.validator_balance import get_predictable_balance

        exit_balance = get_predictable_balance(validator)

        iterator._eject_validator(gid)

        assert ms.total_stake == initial_stake - exit_balance
        assert nos.total_stake == initial_stake - exit_balance
