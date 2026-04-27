from unittest.mock import Mock

import pytest

from src.constants import CURATED_V1_TYPE, CURATED_V2_TYPE, FAR_FUTURE_EPOCH, MIN_ACTIVATION_BALANCE
from src.modules.common.types import ChainConfig
from src.providers.execution.contracts.meta_registry import ExternalOperator, OperatorGroup, SubNodeOperator
from src.services.exit_order_iterator import (
    CuratedModuleNotFoundError,
    ModulesWithSameTypeError,
    NodeOperatorAlreadyGroupedError,
    NodeOperatorExpectedToBeInCMv1Error,
    NodeOperatorStats,
    StakingModuleStats,
    ValidatorExitIterator,
    WeightsNotUpdatedError,
)
from src.types import Gwei, NodeOperatorId, StakingModuleId
from src.utils.validator_balance import get_predictable_balance
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
    # total = 1000 vals worth of balance; threshold = 15% → max_allowed = 150 vals
    iterator.total_lido_predictable_balance = Gwei(1000 * 32 * 10**9)
    sm2 = make_staking_module(2, threshold=int(0.15 * 10000))
    no2 = make_node_operator(2, sm2)

    # sm2 has 200 vals' balance; excess above 150 = 50 vals' worth
    ms2 = StakingModuleStats(
        staking_module=sm2,
        predictable_balance=Gwei(200 * 32 * 10**9),
        total_stake=Gwei(200 * 32 * 10**9),
        total_weight=10.0,
    )

    # force_exit_to=50, soft_exit_to=25, predictable_validators=2000 → both over target
    # total_stake equals target (2000 * 10.0 / 10.0 = 2000 vals) → deviation = 0
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

    res2 = iterator._no_predicate(nos2)
    # force: -(2000 - 50) = -1950
    assert res2[0] == -(2000 - 50)
    # soft:  -(2000 - 25) = -1975
    assert res2[1] == -(2000 - 25)
    # share: -(200*32e9 - 150*32e9) = -(50 * 32e9)
    assert res2[2] == -(50 * 32 * 10**9)
    # target stake deviation: total_stake = target → 0
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
    # 1 exitable validator, force_exit_to=2 → force_predicate=max(1-2,0)=0, no exit needed
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
def test_no_target_balance_deviation_predicate(iterator):
    """_no_target_balance_deviation_predicate returns total_stake - target_stake."""
    sm = make_staking_module(1)
    no = make_node_operator(1, sm)
    ms = StakingModuleStats(staking_module=sm, total_stake=Gwei(1000 * 10**9), total_weight=10.0)

    # Equal to target → deviation is 0
    # target = 1000e9 * 5.0 / 10.0 = 500e9
    nos_at_target = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        total_stake=Gwei(500 * 10**9),
        weight=5.0,
    )
    assert iterator._no_target_balance_deviation_predicate(nos_at_target) == 0

    # Below target → negative deviation (lower exit priority)
    nos_below = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        total_stake=Gwei(100 * 10**9),
        weight=5.0,
    )
    # target = 500e9, deviation = 100e9 - 500e9 = -400e9
    assert iterator._no_target_balance_deviation_predicate(nos_below) == Gwei(-400 * 10**9)

    # Above target → positive deviation (higher exit priority)
    nos_above = NodeOperatorStats(
        node_operator=no,
        module_stats=ms,
        predictable_validators=1,
        total_stake=Gwei(800 * 10**9),
        weight=5.0,
    )
    # target = 500e9, deviation = 800e9 - 500e9 = 300e9
    assert iterator._no_target_balance_deviation_predicate(nos_above) == Gwei(300 * 10**9)


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

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        iterator._process_group(group, cm_v1, cm_v2)

        assert nos_int1.internal_operator_group is not None
        assert nos_int2.internal_operator_group is not None
        assert nos_ext1.external_operator_group is not None
        assert nos_ext2.external_operator_group is not None
        # external_balance = 50 + 30 = 80, added to cm_v2 total_stake
        assert ms_v2.total_stake == Gwei(80 * 10**9)
        # internal_balance = 100 + 200 = 300, split equally among 2 externals = 150 each
        assert nos_ext1.total_stake == Gwei(150 * 10**9)
        assert nos_ext2.total_stake == Gwei(150 * 10**9)
        # internal_weight = 4.0 + 6.0 = 10.0, split equally among 2 externals = 5.0 each
        assert nos_ext1.weight == 1.0 + 5.0
        assert nos_ext2.weight == 2.0 + 5.0
        # internal_balance added to cm_v1 total_stake
        assert ms_v1.total_stake == Gwei(300 * 10**9)
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
        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id))],
        )

        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        with pytest.raises(NodeOperatorAlreadyGroupedError):
            iterator._process_group(group, cm_v1, cm_v2)

        # Same NO in external and internal
        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[ExternalOperator(data=self._make_ext_data(sm_v2.id, no_int.id))],
        )

        with pytest.raises(NodeOperatorExpectedToBeInCMv1Error):
            iterator._process_group(group, cm_v1, cm_v2)

    def test_process_group__already_grouped_external__raises_error(self, iterator):
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1)
        no_ext = make_node_operator(5, sm_v1)
        nos_ext = NodeOperatorStats(node_operator=no_ext, module_stats=ms_v1, external_operator_group=Mock())
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {(sm_v1.id, no_ext.id): nos_ext}
        group = OperatorGroup(
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

        exit_balance = get_predictable_balance(validator)

        iterator._eject_validator(gid)

        assert ms.total_stake == initial_stake - exit_balance
        assert nos.total_stake == initial_stake - exit_balance


@pytest.mark.unit
class TestMakeExitPredicate:
    def test_make_exit_predicate__active_validator__is_exitable(self, iterator):
        gid = (StakingModuleId(1), NodeOperatorId(1))
        indexes = {gid: []}
        filt = ValidatorExitIterator._make_exit_predicate(gid, indexes)

        active_validator = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
        )
        assert filt(active_validator) is True

    def test_make_exit_predicate__on_exit__not_exitable(self, iterator):
        gid = (StakingModuleId(1), NodeOperatorId(1))
        indexes = {gid: []}
        filt = ValidatorExitIterator._make_exit_predicate(gid, indexes)

        on_exit_validator = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=100),
        )
        assert filt(on_exit_validator) is False

    def test_make_exit_predicate__recently_requested__not_exitable(self, iterator):
        gid = (StakingModuleId(1), NodeOperatorId(1))
        v = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
        )
        indexes = {gid: [v.index]}
        filt = ValidatorExitIterator._make_exit_predicate(gid, indexes)

        assert filt(v) is False

    def test_make_exit_predicate__consolidating_as_source__not_exitable(self, iterator):
        gid = (StakingModuleId(1), NodeOperatorId(1))
        indexes = {gid: []}
        filt = ValidatorExitIterator._make_exit_predicate(gid, indexes)

        consolidating_validator = LidoValidatorFactory.build(
            validator=ValidatorStateFactory.build(exit_epoch=FAR_FUTURE_EPOCH),
            consolidating_as_source=Mock(),
        )
        assert filt(consolidating_validator) is False


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
        sm1 = make_staking_module(1)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2)
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
        sm1 = make_staking_module(1)
        ms1 = StakingModuleStats(staking_module=sm1)
        iterator.module_stats = {sm1.id: ms1}

        mock_contract = Mock()
        mock_contract.get_type.return_value = CURATED_V1_TYPE
        iterator.w3.eth.contract = Mock(return_value=mock_contract)

        with pytest.raises(CuratedModuleNotFoundError):
            iterator._fetch_curated_modules()

    def test_fetch_curated_modules__missing_v1__raises_error(self, iterator):
        sm1 = make_staking_module(1)
        ms1 = StakingModuleStats(staking_module=sm1)
        iterator.module_stats = {sm1.id: ms1}

        mock_contract = Mock()
        mock_contract.get_type.return_value = CURATED_V2_TYPE
        iterator.w3.eth.contract = Mock(return_value=mock_contract)

        with pytest.raises(CuratedModuleNotFoundError):
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
        group = OperatorGroup(
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
        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=NodeOperatorId(1), share=100)],
            external_operators=[ExternalOperator(data=bytes(10))],
        )
        assert group.has_connection() is True

    def test_is_fulfilled__empty_sub_operators__returns_false(self):
        group = OperatorGroup(
            sub_node_operators=[],
            external_operators=[ExternalOperator(data=bytes(10))],
        )
        assert group.has_connection() is False

    def test_is_fulfilled__empty_external_operators__returns_false(self):
        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=NodeOperatorId(1), share=100)],
            external_operators=[],
        )
        assert group.has_connection() is False

    def test_is_fulfilled__both_empty__returns_false(self):
        group = OperatorGroup(
            sub_node_operators=[],
            external_operators=[],
        )
        assert group.has_connection() is False


@pytest.mark.unit
class TestModulesWithSameTypeError:
    def test_fetch_curated_modules__duplicate_v1__raises_error(self, iterator):
        sm1 = make_staking_module(1)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2)
        sm2.staking_module_address = "0x" + "b" * 40
        iterator.module_stats = {
            sm1.id: StakingModuleStats(staking_module=sm1),
            sm2.id: StakingModuleStats(staking_module=sm2),
        }

        mock_contract = Mock()
        mock_contract.get_type.return_value = CURATED_V1_TYPE
        iterator.w3.eth.contract = Mock(return_value=mock_contract)

        with pytest.raises(ModulesWithSameTypeError, match="v1"):
            iterator._fetch_curated_modules()

    def test_fetch_curated_modules__duplicate_v2__raises_error(self, iterator):
        sm1 = make_staking_module(1)
        sm1.staking_module_address = "0x" + "a" * 40
        sm2 = make_staking_module(2)
        sm2.staking_module_address = "0x" + "b" * 40
        iterator.module_stats = {
            sm1.id: StakingModuleStats(staking_module=sm1),
            sm2.id: StakingModuleStats(staking_module=sm2),
        }

        mock_contract = Mock()
        mock_contract.get_type.return_value = CURATED_V2_TYPE
        iterator.w3.eth.contract = Mock(return_value=mock_contract)

        with pytest.raises(ModulesWithSameTypeError, match="v2"):
            iterator._fetch_curated_modules()


@pytest.mark.unit
class TestDecreaseAffectedStake:
    @staticmethod
    def _make_ext_data(sm_id, no_id):
        return bytes([0, sm_id]) + no_id.to_bytes(8, byteorder='big')

    def test_no_group__only_decreases_own_module_and_no(self, iterator):
        """When NO has no group, only its own module and NO stats are decreased."""
        sm = make_staking_module(1)
        ms = StakingModuleStats(staking_module=sm, total_stake=Gwei(100 * 10**9))
        no = make_node_operator(1, sm)
        nos = NodeOperatorStats(node_operator=no, module_stats=ms, total_stake=Gwei(60 * 10**9))
        gid = (sm.id, no.id)
        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}

        exit_balance = Gwei(32 * 10**9)
        iterator._decrease_affected_stake(gid, exit_balance)

        assert ms.total_stake == Gwei(68 * 10**9)
        assert nos.total_stake == Gwei(28 * 10**9)

    def test_internal_exit__propagates_to_external_operators(self, iterator):
        """When an internal (CMv2) NO exits, stake is propagated to external (CMv1) NOs."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, total_stake=Gwei(200 * 10**9))
        ms_v1 = StakingModuleStats(staking_module=sm_v1, total_stake=Gwei(300 * 10**9))

        no_int = make_node_operator(10, sm_v2)
        no_ext1 = make_node_operator(20, sm_v1)
        no_ext2 = make_node_operator(21, sm_v1)

        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext1.id)),
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext2.id)),
            ],
        )

        nos_int = NodeOperatorStats(
            node_operator=no_int,
            module_stats=ms_v2,
            total_stake=Gwei(100 * 10**9),
            internal_operator_group=group,
        )
        nos_ext1 = NodeOperatorStats(
            node_operator=no_ext1,
            module_stats=ms_v1,
            total_stake=Gwei(150 * 10**9),
        )
        nos_ext2 = NodeOperatorStats(
            node_operator=no_ext2,
            module_stats=ms_v1,
            total_stake=Gwei(150 * 10**9),
        )

        gid_int = (sm_v2.id, no_int.id)
        gid_ext1 = (sm_v1.id, no_ext1.id)
        gid_ext2 = (sm_v1.id, no_ext2.id)
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            gid_int: nos_int,
            gid_ext1: nos_ext1,
            gid_ext2: nos_ext2,
        }

        exit_balance = Gwei(32 * 10**9)
        iterator._decrease_affected_stake(gid_int, exit_balance)

        # Own module and NO decreased
        assert ms_v2.total_stake == Gwei(200 * 10**9 - 32 * 10**9)
        assert nos_int.total_stake == Gwei(100 * 10**9 - 32 * 10**9)
        # Cross-module: cm_v1 module stats decreased
        assert ms_v1.total_stake == Gwei(300 * 10**9 - 32 * 10**9)
        # Each external NO gets equal share: 32 / 2 = 16
        assert nos_ext1.total_stake == Gwei(150 * 10**9 - 16 * 10**9)
        assert nos_ext2.total_stake == Gwei(150 * 10**9 - 16 * 10**9)

    def test_external_exit__propagates_to_internal_operators_by_weight(self, iterator):
        """When an external (CMv1) NO exits, stake is propagated to internal (CMv2) NOs by weight."""
        sm_v2 = make_staking_module(2)
        sm_v1 = make_staking_module(1)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, total_stake=Gwei(200 * 10**9))
        ms_v1 = StakingModuleStats(staking_module=sm_v1, total_stake=Gwei(300 * 10**9))

        no_ext = make_node_operator(20, sm_v1)
        no_int1 = make_node_operator(10, sm_v2)
        no_int2 = make_node_operator(11, sm_v2)

        group = OperatorGroup(
            sub_node_operators=[
                SubNodeOperator(node_operator_id=no_int1.id, share=50),
                SubNodeOperator(node_operator_id=no_int2.id, share=50),
            ],
            external_operators=[
                ExternalOperator(data=self._make_ext_data(sm_v1.id, no_ext.id)),
            ],
        )

        nos_ext = NodeOperatorStats(
            node_operator=no_ext,
            module_stats=ms_v1,
            total_stake=Gwei(100 * 10**9),
            external_operator_group=group,
        )
        nos_int1 = NodeOperatorStats(
            node_operator=no_int1,
            module_stats=ms_v2,
            total_stake=Gwei(80 * 10**9),
            weight=4.0,
        )
        nos_int2 = NodeOperatorStats(
            node_operator=no_int2,
            module_stats=ms_v2,
            total_stake=Gwei(120 * 10**9),
            weight=6.0,
        )

        gid_ext = (sm_v1.id, no_ext.id)
        gid_int1 = (sm_v2.id, no_int1.id)
        gid_int2 = (sm_v2.id, no_int2.id)
        iterator.cm_v2_id = sm_v2.id
        iterator.module_stats = {sm_v2.id: ms_v2, sm_v1.id: ms_v1}
        iterator.node_operators_stats = {
            gid_ext: nos_ext,
            gid_int1: nos_int1,
            gid_int2: nos_int2,
        }

        exit_balance = Gwei(50 * 10**9)
        iterator._decrease_affected_stake(gid_ext, exit_balance)

        # Own module and NO decreased
        assert ms_v1.total_stake == Gwei(300 * 10**9 - 50 * 10**9)
        assert nos_ext.total_stake == Gwei(100 * 10**9 - 50 * 10**9)
        # Cross-module: cm_v2 module stats decreased
        assert ms_v2.total_stake == Gwei(200 * 10**9 - 50 * 10**9)
        # Internal NOs decreased by weight: total_weight = 4+6 = 10
        # int1: 50 * 4/10 = 20, int2: 50 * 6/10 = 30
        assert nos_int1.total_stake == Gwei(80 * 10**9 - 20 * 10**9)
        assert nos_int2.total_stake == Gwei(120 * 10**9 - 30 * 10**9)

    def test_internal_exit__unfulfilled_group__no_cross_module_propagation(self, iterator):
        """When group is not fulfilled, only own module/NO are decreased."""
        sm_v2 = make_staking_module(2)
        ms_v2 = StakingModuleStats(staking_module=sm_v2, total_stake=Gwei(200 * 10**9))

        no_int = make_node_operator(10, sm_v2)
        # Group with no external operators — not fulfilled
        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=no_int.id, share=100)],
            external_operators=[],
        )

        nos_int = NodeOperatorStats(
            node_operator=no_int,
            module_stats=ms_v2,
            total_stake=Gwei(100 * 10**9),
            internal_operator_group=group,
        )

        gid = (sm_v2.id, no_int.id)
        iterator.module_stats = {sm_v2.id: ms_v2}
        iterator.node_operators_stats = {gid: nos_int}

        exit_balance = Gwei(32 * 10**9)
        iterator._decrease_affected_stake(gid, exit_balance)

        # Only own module and NO decreased, no cross-module propagation
        assert ms_v2.total_stake == Gwei(200 * 10**9 - 32 * 10**9)
        assert nos_int.total_stake == Gwei(100 * 10**9 - 32 * 10**9)

    def test_external_exit__unfulfilled_group__no_cross_module_propagation(self, iterator):
        """When external NO is in an unfulfilled group (no sub_node_operators), no cross-module propagation."""
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        ms_v1 = StakingModuleStats(staking_module=sm_v1, total_stake=Gwei(300 * 10**9))
        ms_v2 = StakingModuleStats(staking_module=sm_v2, total_stake=Gwei(200 * 10**9))

        no_ext = make_node_operator(20, sm_v1)
        unfulfilled_group = OperatorGroup(sub_node_operators=[], external_operators=[])

        nos_ext = NodeOperatorStats(
            node_operator=no_ext,
            module_stats=ms_v1,
            total_stake=Gwei(100 * 10**9),
            external_operator_group=unfulfilled_group,
        )
        gid = (sm_v1.id, no_ext.id)
        iterator.module_stats = {sm_v1.id: ms_v1, sm_v2.id: ms_v2}
        iterator.node_operators_stats = {gid: nos_ext}
        iterator.cm_v2_id = sm_v2.id

        exit_balance = Gwei(32 * 10**9)
        iterator._decrease_affected_stake(gid, exit_balance)

        assert ms_v1.total_stake == Gwei(300 * 10**9 - 32 * 10**9)
        assert nos_ext.total_stake == Gwei(100 * 10**9 - 32 * 10**9)
        assert ms_v2.total_stake == Gwei(200 * 10**9), "cm_v2 not affected when group unfulfilled"


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

        group = OperatorGroup(
            sub_node_operators=[SubNodeOperator(node_operator_id=no1.id, share=100)],
            external_operators=[],
        )
        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())
        iterator._process_group(group, cm_v1, cm_v2)

        # Internal NO should be marked grouped
        assert nos1.internal_operator_group is not None
        # No cross-accounting: total_stake unchanged, module total_stake unchanged
        assert nos1.total_stake == Gwei(0)
        assert ms_v2.total_stake == Gwei(0)


@pytest.mark.unit
class TestFinalizeAndReportLimits:
    def test_finalize_cm_v1_and_cm_v2_stats__sets_cm_v2_id(self, iterator):
        """_finalize_cm_v1_and_cm_v2_stats sets self.cm_v2_id to the cm_v2 module id."""
        sm_v1 = make_staking_module(1)
        sm_v2 = make_staking_module(2)
        cm_v1 = (sm_v1.id, Mock())
        cm_v2 = (sm_v2.id, Mock())

        iterator._fetch_curated_modules = Mock(return_value=(cm_v1, cm_v2))
        iterator._setup_weights = Mock()
        iterator._setup_meta_connections = Mock()

        iterator._finalize_cm_v1_and_cm_v2_stats()

        assert iterator.cm_v2_id == sm_v2.id
        iterator._setup_weights.assert_called_once_with(cm_v2)
        iterator._setup_meta_connections.assert_called_once_with(cm_v1, cm_v2)

    def test_get_report_limits__sets_exit_limit_in_gwei(self, iterator):
        """_get_report_limits sets exit_limit_in_gwei from oracle report limits."""
        iterator.w3.lido_contracts.oracle_report_sanity_checker.get_oracle_report_limits.return_value = Mock(
            max_balance_exit_requested_per_report_in_eth=100
        )
        iterator._get_report_limits()

        assert iterator.exit_limit_in_gwei == Gwei(100 * 10**9)


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
        assert ms.total_stake == expected_balance
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
            total_stake=Gwei(32 * 10**9),
            total_weight=weight,
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch)

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
        iterator.max_current_exit_balance = Gwei(0)
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        result_gid, result_val = iterator.__next__()

        assert result_gid == gid
        assert result_val is validator

    def test_next__exceeds_limit__raises_stop_iteration(self, iterator):
        """__next__ raises StopIteration when exit limit is exceeded."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm)
        gid = (sm.id, no.id)
        weight = float(10 * 10000)
        ms = StakingModuleStats(
            staking_module=sm,
            predictable_balance=Gwei(32 * 10**9),
            total_stake=Gwei(32 * 10**9),
            total_weight=weight,
        )
        validator = LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch)

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
        iterator.max_current_exit_balance = Gwei(0)
        iterator.exit_limit_in_gwei = Gwei(0)  # limit already at 0, any exit exceeds it

        with pytest.raises(StopIteration):
            iterator.__next__()

    def test_next__empty_exitable_validators__raises_stop_iteration(self, iterator):
        """__next__ raises StopIteration when no NO has exitable validators."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm)
        gid = (sm.id, no.id)
        weight = float(10 * 10000)
        ms = StakingModuleStats(staking_module=sm, total_weight=weight)
        nos = NodeOperatorStats(node_operator=no, module_stats=ms, weight=weight)

        iterator.module_stats = {sm.id: ms}
        iterator.node_operators_stats = {gid: nos}
        iterator.exitable_validators = {gid: []}
        iterator.total_lido_predictable_balance = Gwei(0)
        iterator.max_current_exit_balance = Gwei(0)
        iterator.exit_limit_in_gwei = Gwei(100_000 * 10**9)

        with pytest.raises(StopIteration):
            iterator.__next__()

    def test_iter__initializes_all_state(self, iterator):
        """__iter__ sets up max_current_exit_balance=0 and returns self."""
        iterator._reset_iterator_data = Mock()
        iterator._prepare_data_structure = Mock()
        iterator._calculate_lido_stats = Mock()
        iterator._get_report_limits = Mock()

        result = iter(iterator)

        assert result is iterator
        assert iterator.max_current_exit_balance == Gwei(0)
        iterator._reset_iterator_data.assert_called_once()
        iterator._prepare_data_structure.assert_called_once()
        iterator._calculate_lido_stats.assert_called_once()
        iterator._get_report_limits.assert_called_once()


@pytest.mark.unit
class TestGetRemainingForcedEdgeCases:
    def test_limit_hit_during_forced__returns_partial_list(self, iterator):
        """When exit limit is hit mid-run, only validators collected before the limit are returned."""
        sm = make_staking_module(1)
        no = make_node_operator(1, sm, total_dep=3, target=0, limit_mode=NodeOperatorLimitMode.FORCE)
        gid = (sm.id, no.id)
        ms = StakingModuleStats(staking_module=sm, predictable_balance=Gwei(96 * 10**9), total_stake=Gwei(96 * 10**9))
        validators = [
            LidoValidatorFactory.build_with_activation_epoch_bound(iterator.blockstamp.ref_epoch) for _ in range(3)
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
        iterator.max_current_exit_balance = Gwei(0)

        result = iterator.get_remaining_forced_validators()

        assert len(result) == 1, "Only the first validator fits within the limit"
        assert result[0][0] == gid

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
        iterator.max_current_exit_balance = Gwei(0)

        result = iterator.get_remaining_forced_validators()

        assert result == [], "Empty list when no validators are available despite forced exit need"
