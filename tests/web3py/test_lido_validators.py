from unittest.mock import Mock, patch

import pytest

from src.constants import COMPOUNDING_WITHDRAWAL_PREFIX, ETH1_ADDRESS_WITHDRAWAL_PREFIX
from src.modules.oracles.accounting.types import BeaconStat
from src.web3py.extensions.lido_validators import (
    CountOfKeysDiffersException,
    LidoValidatorsProvider,
    NodeOperator,
    NodeOperatorLimitMode,
)
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.no_registry import (
    LidoKeyFactory,
    LidoValidatorFactory,
    NodeOperatorFactory,
    StakingModuleFactory,
    ValidatorFactory,
)


# Hex values used in pending-deposit tests (lengths don't matter since BLS is mocked)
_PUBKEY = '0x' + 'ab' * 4
_SIGNATURE = '0x' + 'ef' * 4
_GENESIS_FORK_VERSION = '0x01020304'
_LIDO_WC = ETH1_ADDRESS_WITHDRAWAL_PREFIX + '0' * 62
_NON_LIDO_WC = '0x03' + '0' * 62


blockstamp = ReferenceBlockStampFactory.build()


@pytest.mark.unit
def test_get_lido_validators(web3):
    validators = ValidatorFactory.batch(30)
    lido_keys = LidoKeyFactory.generate_for_validators(validators[:10])
    lido_keys.extend(LidoKeyFactory.batch(10))

    web3.lido_validators._kapi_sanity_check = Mock()

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)
    web3.cc.get_pending_deposits = Mock(return_value=[])
    web3.cc.get_pending_consolidations = Mock(return_value=[])
    web3.cc.get_validators_by_indexes = Mock(return_value={})

    lido_validators = web3.lido_validators.get_active_lido_validators(blockstamp)

    assert len(lido_validators) == 10
    assert len(lido_keys) != len(lido_validators)
    assert len(validators) != len(lido_validators)

    for v in lido_validators:
        assert v.lido_id.key == v.validator.pubkey


@pytest.mark.unit
def test_kapi_has_lesser_keys_than_deposited_validators_count(web3):
    validators = ValidatorFactory.batch(10)
    lido_keys = [LidoKeyFactory.build()]

    web3.cc.get_validators = Mock(return_value=validators)
    web3.kac.get_used_lido_keys = Mock(return_value=lido_keys)
    web3.cc.get_pending_deposits = Mock(return_value=[])
    web3.cc.get_pending_consolidations = Mock(return_value=[])
    web3.cc.get_validators_by_indexes = Mock(return_value={})
    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(
            deposited_validators=10,
            beacon_validators=0,
            beacon_balance=0,
        )
    )

    with pytest.raises(CountOfKeysDiffersException):
        web3.lido_validators.get_active_lido_validators(blockstamp)

    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(
            deposited_validators=1,
            beacon_validators=0,
            beacon_balance=0,
        )
    )

    web3.lido_validators.get_active_lido_validators(blockstamp)

    # Keys can exist in KAPI, but no yet represented on CL
    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(
            deposited_validators=0,
            beacon_validators=0,
            beacon_balance=0,
        )
    )

    web3.lido_validators.get_active_lido_validators(blockstamp)


@pytest.mark.unit
def test_get_lido_node_operators_by_modules(web3):
    web3.lido_contracts.staking_router.get_staking_modules = Mock(
        return_value=[
            StakingModuleFactory.build(id=1),
            StakingModuleFactory.build(id=2),
        ]
    )
    web3.lido_contracts.staking_router.get_all_node_operator_digests = Mock(side_effect=lambda x, _: list(range(x.id)))

    result = web3.lido_validators.get_lido_node_operators_by_modules(blockstamp)

    for key, value in result.items():
        assert len(value) == key


@pytest.mark.unit
def test_get_node_operators(web3):
    web3.lido_validators.get_lido_node_operators_by_modules = Mock(
        return_value={
            0: [0, 2, 3],
            1: [1, 5],
        }
    )

    node_operators = web3.lido_validators.get_lido_node_operators(blockstamp)

    assert len(node_operators) == 5


@pytest.mark.unit
def test_get_lido_validators_by_node_operator(web3):
    # 2 NO in one module
    # 1 NO in 2 module
    sm1 = StakingModuleFactory.build(id=1)
    sm2 = StakingModuleFactory.build(id=2)

    web3.lido_validators.get_active_lido_validators = Mock(
        return_value=[
            LidoValidatorFactory.build(
                lido_id=LidoKeyFactory.build(
                    operator_index=1,
                    module_address=sm1.staking_module_address,
                )
            ),
            LidoValidatorFactory.build(
                lido_id=LidoKeyFactory.build(
                    operator_index=1,
                    module_address=sm1.staking_module_address,
                )
            ),
            LidoValidatorFactory.build(
                lido_id=LidoKeyFactory.build(
                    operator_index=1,
                    module_address=sm2.staking_module_address,
                )
            ),
        ]
    )
    web3.lido_validators.get_lido_node_operators = Mock(
        return_value=[
            NodeOperatorFactory.build(
                id=1,
                staking_module=sm1,
            ),
            NodeOperatorFactory.build(
                id=2,
                staking_module=sm1,
            ),
            NodeOperatorFactory.build(
                id=1,
                staking_module=sm2,
            ),
        ]
    )

    no_validators = web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

    assert len(no_validators.keys()) == 3
    assert len(no_validators[(1, 1)]) == 2
    assert len(no_validators[(2, 1)]) == 1


@pytest.mark.unit
def test_get_lido_validators_by_node_operator_inconsistent(web3, caplog):
    validator = LidoValidatorFactory.build()
    web3.lido_validators.get_active_lido_validators = Mock(return_value=[validator])
    web3.lido_validators.get_lido_node_operators = Mock(
        return_value=[
            NodeOperatorFactory.build(
                staking_module=StakingModuleFactory.build(
                    staking_module_address=validator.lido_id.module_address,
                ),
            ),
        ]
    )

    web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)
    assert "not exist in staking router" in caplog.text


# ---- get_lido_wc_list ----


@pytest.mark.unit
def test_get_lido_wc_list(web3):
    address = '0xAb' + 'cd' * 19  # 20-byte address
    web3.lido_contracts.lido_locator.withdrawal_vault = Mock(return_value=address)

    wc_list = web3.lido_validators.get_lido_wc_list(blockstamp)

    expected_postfix = '0' * 22 + address[2:].lower()
    assert len(wc_list) == 2
    assert wc_list[0] == ETH1_ADDRESS_WITHDRAWAL_PREFIX + expected_postfix
    assert wc_list[1] == COMPOUNDING_WITHDRAWAL_PREFIX + expected_postfix


# ---- merge_validators_with_keys ----


@pytest.mark.unit
def test_merge_validators_with_keys():
    validators = ValidatorFactory.batch(5)
    matching_keys = LidoKeyFactory.generate_for_validators(validators[:3])
    extra_keys = LidoKeyFactory.batch(2)
    all_keys = matching_keys + extra_keys

    active, pending = LidoValidatorsProvider.compute_lido_validators(all_keys, validators)

    assert len(active) == 3
    assert len(pending) == 2
    for v in active:
        assert v.lido_id.key == v.validator.pubkey


@pytest.mark.unit
def test_merge_validators_with_keys_empty():
    active, pending = LidoValidatorsProvider.compute_lido_validators([], [])
    assert active == []
    assert pending == []


@pytest.mark.unit
def test_merge_validators_with_keys_all_pending():
    # Keys present in KAPI but no validators on CL yet
    keys = LidoKeyFactory.batch(3)
    active, pending = LidoValidatorsProvider.compute_lido_validators(keys, [])
    assert active == []
    assert len(pending) == 3


# ---- _kapi_sanity_check boundary ----


@pytest.mark.unit
def test_kapi_sanity_check_boundary_equal(web3):
    # keys_count == deposited_validators should NOT raise
    web3.lido_contracts.lido.get_beacon_stat = Mock(
        return_value=BeaconStat(deposited_validators=5, beacon_validators=0, beacon_balance=0)
    )
    web3.lido_validators._kapi_sanity_check(5, blockstamp)  # must not raise


# ---- NodeOperator.from_response ----


@pytest.mark.unit
def test_node_operator_from_response():
    staking_module = StakingModuleFactory.build()
    data = (
        1,  # id
        True,  # is_active
        (
            1,  # is_target_limit_active → SOFT
            100,  # target_validators_count
            0,  # _stuck_validators_count (deprecated)
            5,  # refunded_validators_count
            0,  # _stuck_penalty_end_timestamp (deprecated)
            10,  # total_exited_validators
            50,  # total_deposited_validators
            40,  # depositable_validators_count
        ),
    )

    operator = NodeOperator.from_response(data, staking_module)

    assert operator.id == 1
    assert operator.is_active is True
    assert operator.is_target_limit_active == NodeOperatorLimitMode.SOFT
    assert operator.target_validators_count == 100
    assert operator.refunded_validators_count == 5
    assert operator.total_exited_validators == 10
    assert operator.total_deposited_validators == 50
    assert operator.depositable_validators_count == 40
    assert operator.staking_module is staking_module


@pytest.mark.unit
def test_node_operator_from_response_clamps_limit_mode():
    # is_target_limit_active > 2 should be clamped to FORCE (2)
    staking_module = StakingModuleFactory.build()
    data = (1, True, (99, 0, 0, 0, 0, 0, 0, 0))

    operator = NodeOperator.from_response(data, staking_module)

    assert operator.is_target_limit_active == NodeOperatorLimitMode.FORCE


# ---- get_lido_node_operators_by_modules: empty modules ----


@pytest.mark.unit
def test_get_lido_node_operators_by_modules_empty(web3):
    web3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[])

    result = web3.lido_validators.get_lido_node_operators_by_modules(blockstamp)

    assert result == {}


# ---- get_lido_validators_by_node_operators: empty validators ----


@pytest.mark.unit
def test_get_lido_validators_by_node_operator_empty_validators(web3):
    sm = StakingModuleFactory.build(id=1)
    web3.lido_validators.get_active_lido_validators = Mock(return_value=[])
    web3.lido_validators.get_lido_node_operators = Mock(
        return_value=[
            NodeOperatorFactory.build(id=1, staking_module=sm),
            NodeOperatorFactory.build(id=2, staking_module=sm),
        ]
    )

    result = web3.lido_validators.get_lido_validators_by_node_operators(blockstamp)

    assert len(result) == 2
    assert result[(sm.id, 1)] == []
    assert result[(sm.id, 2)] == []


# ---- get_pending_lido_validators ----


def _setup_pending_validators(web3, pending_lido_keys, pending_deposits):
    """Helper to configure mocks for get_pending_lido_validators."""
    web3.lido_validators.get_lido_wc_list = Mock(return_value=[_LIDO_WC])
    web3.cc.get_genesis = Mock(return_value=Mock(genesis_fork_version=_GENESIS_FORK_VERSION))
    web3.cc.get_pending_deposits = Mock(return_value=pending_deposits)
    web3.lido_validators._get_lido_validators_with_keys = Mock(return_value=([], pending_lido_keys))


def _make_deposit(pubkey=_PUBKEY, wc=_LIDO_WC):
    return Mock(pubkey=pubkey, withdrawal_credentials=wc, amount=32_000_000_000, signature=_SIGNATURE)


@pytest.mark.unit
def test_get_pending_lido_validators_non_lido_pubkey_skipped(web3):
    # Deposit whose pubkey is not in the set of Lido pending keys → ignored
    lido_key = LidoKeyFactory.build(key=_PUBKEY)
    unknown_deposit = _make_deposit(pubkey='0xdeadbeef')
    _setup_pending_validators(web3, [lido_key], [unknown_deposit])

    result = web3.lido_validators.get_pending_lido_validators(blockstamp)

    assert result == {}


@pytest.mark.unit
def test_get_pending_lido_validators_happy_path(web3):
    # Valid deposit with Lido WC → added to result
    lido_key = LidoKeyFactory.build(key=_PUBKEY)
    deposit = _make_deposit(wc=_LIDO_WC)
    _setup_pending_validators(web3, [lido_key], [deposit])

    with patch('src.web3py.extensions.lido_validators.is_valid_deposit_signature', return_value=True):
        result = web3.lido_validators.get_pending_lido_validators(ReferenceBlockStampFactory.build())

    assert _PUBKEY in result
    key, deposits = result[_PUBKEY]
    assert key is lido_key
    assert deposits == [deposit]


@pytest.mark.unit
def test_get_pending_lido_validators_frontrun_attack(web3, caplog):
    # Valid BLS signature but non-Lido withdrawal credentials → front-run attack
    lido_key = LidoKeyFactory.build(key=_PUBKEY)
    deposit = _make_deposit(wc=_NON_LIDO_WC)
    _setup_pending_validators(web3, [lido_key], [deposit])

    with patch('src.web3py.extensions.lido_validators.is_valid_deposit_signature', return_value=True):
        result = web3.lido_validators.get_pending_lido_validators(ReferenceBlockStampFactory.build())

    assert result == {}
    assert 'front run' in caplog.text.lower() or 'frontrun' in caplog.text.lower() or 'front-run' in caplog.text.lower()


@pytest.mark.unit
def test_get_pending_lido_validators_second_deposit_appended(web3):
    # Two deposits for the same valid key → second one appended to the list
    lido_key = LidoKeyFactory.build(key=_PUBKEY)
    deposit1 = _make_deposit(wc=_LIDO_WC)
    deposit2 = _make_deposit(wc=_LIDO_WC)
    _setup_pending_validators(web3, [lido_key], [deposit1, deposit2])

    with patch('src.web3py.extensions.lido_validators.is_valid_deposit_signature', return_value=True):
        result = web3.lido_validators.get_pending_lido_validators(ReferenceBlockStampFactory.build())

    assert _PUBKEY in result
    _, deposits = result[_PUBKEY]
    assert deposits == [deposit1, deposit2]


@pytest.mark.unit
def test_get_pending_lido_validators_second_deposit_for_invalid_key_skipped(web3):
    # First deposit is a frontrun (bad WC), second deposit for same key is skipped
    lido_key = LidoKeyFactory.build(key=_PUBKEY)
    deposit1 = _make_deposit(wc=_NON_LIDO_WC)
    deposit2 = _make_deposit(wc=_LIDO_WC)
    _setup_pending_validators(web3, [lido_key], [deposit1, deposit2])

    with patch('src.web3py.extensions.lido_validators.is_valid_deposit_signature', return_value=True):
        result = web3.lido_validators.get_pending_lido_validators(ReferenceBlockStampFactory.build())

    assert result == {}


@pytest.mark.unit
def test_get_active_lido_validators__with_empty_data(web3):
    """
    Test that `get_active_lido_validators` handles empty data inputs correctly.
    """
    blockstamp = ReferenceBlockStampFactory.build()
    web3.lido_validators._get_lido_validators_with_keys = Mock(return_value=([], []))
    web3.cc.get_pending_deposits = Mock(return_value=[])
    web3.cc.get_pending_consolidations = Mock(return_value={})
    web3.cc.get_validators_by_indexes = Mock(return_value={})

    active_validators = web3.lido_validators.get_active_lido_validators(blockstamp)

    assert active_validators == []
    web3.cc.get_pending_deposits.assert_called_once_with(blockstamp)
    web3.cc.get_pending_consolidations.assert_called_once_with(blockstamp)
    web3.lido_validators._get_lido_validators_with_keys.assert_called_once_with(blockstamp)


@pytest.mark.unit
def test_get_active_lido_validators__with_valid_data(web3):
    """
    Test `get_active_lido_validators` returns correct outputs based on mock data.
    """
    blockstamp = ReferenceBlockStampFactory.build()
    mock_validators = LidoValidatorFactory.batch(5)
    deposits_map = {mock_validators[0].validator.pubkey: [Mock(amount=1000)]}

    web3.lido_validators._get_lido_validators_with_keys = Mock(return_value=(mock_validators, []))
    web3.cc.get_pending_deposits = Mock(return_value=[Mock(pubkey=mock_validators[0].validator.pubkey, amount=1000)])
    web3.cc.get_validators_by_indexes = Mock(return_value={v.index: v for v in mock_validators})
    web3.cc.get_pending_consolidations = Mock(return_value=[])

    active_validators = web3.lido_validators.get_active_lido_validators(blockstamp)

    assert len(active_validators) == len(mock_validators)
    assert sum(len(v.pending_topups) for v in active_validators) == 1
    assert active_validators[0].pending_topups[0].amount == deposits_map[mock_validators[0].validator.pubkey][0].amount


@pytest.mark.unit
def test_get_active_lido_validators__with_slashed_sources(web3):
    """
    Test that consolidation requests whose source validator is slashed are skipped.
    Both validators are still returned — only the consolidation record is dropped.
    """
    blockstamp = ReferenceBlockStampFactory.build()
    validator1, validator2 = LidoValidatorFactory.batch(2)
    validator1.validator.slashed = False
    validator2.validator.slashed = True  # source is slashed → consolidation should be skipped
    mock_validators = [validator1, validator2]

    web3.lido_validators._get_lido_validators_with_keys = Mock(return_value=(mock_validators, []))
    web3.cc.get_pending_deposits = Mock(return_value=[])
    web3.cc.get_validators_by_indexes = Mock(return_value={v.index: v for v in mock_validators})
    web3.cc.get_pending_consolidations = Mock(return_value=[Mock(source_index=validator2.index)])

    active_validators = web3.lido_validators.get_active_lido_validators(blockstamp)

    # All validators are returned regardless of slashed status
    assert len(active_validators) == 2
    # The consolidation from the slashed source must not be recorded
    v2_result = next(v for v in active_validators if v.index == validator2.index)
    assert v2_result.consolidating_as_source is None


@pytest.mark.unit
def test_get_active_lido_validators__handles_multiple_consolidations(web3):
    """
    Test `get_active_lido_validators` handles multiple consolidations correctly.
    """
    blockstamp = ReferenceBlockStampFactory.build()
    mock_validators = LidoValidatorFactory.batch(3)
    # Ensure source validators are not slashed so consolidations are processed
    for v in mock_validators:
        v.validator.slashed = False
    consolidation_data = [
        Mock(source_index=mock_validators[0].index, target_index=mock_validators[1].index),
        Mock(source_index=mock_validators[2].index, target_index=mock_validators[1].index),
    ]

    web3.lido_validators._get_lido_validators_with_keys = Mock(return_value=(mock_validators, []))
    web3.cc.get_pending_deposits = Mock(return_value=[])
    web3.cc.get_validators_by_indexes = Mock(return_value={v.index: v for v in mock_validators})
    web3.cc.get_pending_consolidations = Mock(return_value=consolidation_data)

    active_validators = web3.lido_validators.get_active_lido_validators(blockstamp)

    assert len(active_validators) == len(mock_validators)
    assert active_validators[0].consolidating_as_source is not None
    assert len(active_validators[1].consolidating_as_target) == 2
