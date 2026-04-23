from typing import cast
from unittest.mock import Mock

import pytest
from hexbytes import HexBytes
from web3.exceptions import Web3Exception

import variables
from providers.execution.contracts.cs_parameters_registry import CurveParams
from providers.ipfs import CIDv0, CIDv1
from type_aliases import NodeOperatorId, SlotNumber
from web3py.extensions.staking_module import StakingModuleContracts
from web3py.types import Web3, Web3StakingModule


DUMMY_ADDRESS = "0x9999999999999999999999999999999999999999"

CIDV0_EXAMPLE = "QmYg3rSSqLQm9Cn93EzrWSPFv9cv1FPmsFHJLnhXQiBekc"
CIDV1_EXAMPLE = "bafybeiemxf5abjwjbikoz4mc3a3dla6ual3jsgpdr4cjr3oz3evfyavhwq"

BLOCK_HASH = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


@pytest.fixture()
def blockstamp():
    return Mock(block_hash=BLOCK_HASH)


@pytest.fixture()
def w3(web3: Web3, monkeypatch) -> Web3StakingModule:
    monkeypatch.setattr(variables, "STAKING_MODULE_ADDRESS", DUMMY_ADDRESS)
    monkeypatch.setattr(StakingModuleContracts, "CONTRACT_LOAD_MAX_RETRIES", 1)
    monkeypatch.setattr(StakingModuleContracts, "CONTRACT_LOAD_RETRY_DELAY", 0)

    web3.attach_modules({"staking_module": StakingModuleContracts})
    return cast(Web3StakingModule, web3)


@pytest.mark.unit
def test_init_raises_when_address_not_set(web3: Web3, monkeypatch):
    monkeypatch.setattr(variables, "STAKING_MODULE_ADDRESS", "")

    with pytest.raises(ValueError, match="STAKING_MODULE_ADDRESS is not set"):
        web3.attach_modules({"staking_module": StakingModuleContracts})


@pytest.mark.unit
def test_init_loads_contracts(w3: Web3StakingModule):
    sm = w3.staking_module
    assert sm.module is not None
    assert sm.oracle is not None
    assert sm.params is not None
    assert sm.strikes is not None
    assert sm.accounting is not None
    assert sm.fee_distributor is not None


@pytest.mark.unit
def test_load_contracts_retries_and_raises(web3: Web3, monkeypatch):
    monkeypatch.setattr(variables, "STAKING_MODULE_ADDRESS", DUMMY_ADDRESS)
    monkeypatch.setattr(StakingModuleContracts, "CONTRACT_LOAD_MAX_RETRIES", 3)
    monkeypatch.setattr(StakingModuleContracts, "CONTRACT_LOAD_RETRY_DELAY", 0)
    failing_contract = Mock(side_effect=Web3Exception("contract load failed"))
    monkeypatch.setattr(web3.eth, "contract", failing_contract)

    with pytest.raises(Web3Exception, match="Failed to load contracts"):
        web3.attach_modules({"staking_module": StakingModuleContracts})

    assert failing_contract.call_count == 3


@pytest.mark.unit
def test_get_last_processing_ref_slot(w3: Web3StakingModule, blockstamp):
    expected_slot = SlotNumber(12345)
    w3.staking_module.oracle.get_last_processing_ref_slot = Mock(return_value=expected_slot)

    result = w3.staking_module.get_last_processing_ref_slot(blockstamp)

    assert result == expected_slot
    w3.staking_module.oracle.get_last_processing_ref_slot.assert_called_once_with(BLOCK_HASH)


@pytest.mark.unit
def test_get_rewards_tree_root(w3: Web3StakingModule, blockstamp):
    expected = HexBytes(b"\x01" * 32)
    w3.staking_module.fee_distributor.tree_root = Mock(return_value=expected)

    result = w3.staking_module.get_rewards_tree_root(blockstamp)

    assert result == expected
    w3.staking_module.fee_distributor.tree_root.assert_called_once_with(BLOCK_HASH)


@pytest.mark.unit
def test_get_rewards_tree_cid_returns_none_for_empty(w3: Web3StakingModule, blockstamp):
    w3.staking_module.fee_distributor.tree_cid = Mock(return_value="")

    result = w3.staking_module.get_rewards_tree_cid(blockstamp)

    assert result is None


@pytest.mark.unit
def test_get_rewards_tree_cid_returns_cidv0(w3: Web3StakingModule, blockstamp):
    w3.staking_module.fee_distributor.tree_cid = Mock(return_value=CIDV0_EXAMPLE)

    result = w3.staking_module.get_rewards_tree_cid(blockstamp)

    assert isinstance(result, CIDv0)
    assert str(result) == CIDV0_EXAMPLE


@pytest.mark.unit
def test_get_rewards_tree_cid_returns_cidv1(w3: Web3StakingModule, blockstamp):
    w3.staking_module.fee_distributor.tree_cid = Mock(return_value=CIDV1_EXAMPLE)

    result = w3.staking_module.get_rewards_tree_cid(blockstamp)

    assert isinstance(result, CIDv1)
    assert str(result) == CIDV1_EXAMPLE


@pytest.mark.unit
def test_get_strikes_tree_root(w3: Web3StakingModule, blockstamp):
    expected = HexBytes(b"\x02" * 32)
    w3.staking_module.strikes.tree_root = Mock(return_value=expected)

    result = w3.staking_module.get_strikes_tree_root(blockstamp)

    assert result == expected
    w3.staking_module.strikes.tree_root.assert_called_once_with(BLOCK_HASH)


@pytest.mark.unit
def test_get_strikes_tree_cid_returns_none_for_empty(w3: Web3StakingModule, blockstamp):
    w3.staking_module.strikes.tree_cid = Mock(return_value="")

    result = w3.staking_module.get_strikes_tree_cid(blockstamp)

    assert result is None


@pytest.mark.unit
def test_get_strikes_tree_cid_returns_cidv0(w3: Web3StakingModule, blockstamp):
    w3.staking_module.strikes.tree_cid = Mock(return_value=CIDV0_EXAMPLE)

    result = w3.staking_module.get_strikes_tree_cid(blockstamp)

    assert isinstance(result, CIDv0)
    assert str(result) == CIDV0_EXAMPLE


@pytest.mark.unit
def test_get_strikes_tree_cid_returns_cidv1(w3: Web3StakingModule, blockstamp):
    w3.staking_module.strikes.tree_cid = Mock(return_value=CIDV1_EXAMPLE)

    result = w3.staking_module.get_strikes_tree_cid(blockstamp)

    assert isinstance(result, CIDv1)
    assert str(result) == CIDV1_EXAMPLE


@pytest.mark.unit
def test_get_curve_params(w3: Web3StakingModule, blockstamp):
    no_id = NodeOperatorId(0)
    curve_id = 2

    mock_perf_coeffs = Mock()
    mock_perf_leeway = Mock()
    mock_reward_share = Mock()
    mock_strikes_params = Mock()

    w3.staking_module.accounting.get_bond_curve_id = Mock(return_value=curve_id)
    w3.staking_module.params.get_performance_coefficients = Mock(return_value=mock_perf_coeffs)
    w3.staking_module.params.get_performance_leeway_data = Mock(return_value=mock_perf_leeway)
    w3.staking_module.params.get_reward_share_data = Mock(return_value=mock_reward_share)
    w3.staking_module.params.get_strikes_params = Mock(return_value=mock_strikes_params)

    result = w3.staking_module.get_curve_params(no_id, blockstamp)

    assert isinstance(result, CurveParams)
    assert result.perf_coeffs is mock_perf_coeffs
    assert result.perf_leeway_data is mock_perf_leeway
    assert result.reward_share_data is mock_reward_share
    assert result.strikes_params is mock_strikes_params

    w3.staking_module.accounting.get_bond_curve_id.assert_called_once_with(no_id, BLOCK_HASH)
    w3.staking_module.params.get_performance_coefficients.assert_called_once_with(curve_id, BLOCK_HASH)
    w3.staking_module.params.get_performance_leeway_data.assert_called_once_with(curve_id, BLOCK_HASH)
    w3.staking_module.params.get_reward_share_data.assert_called_once_with(curve_id, BLOCK_HASH)
    w3.staking_module.params.get_strikes_params.assert_called_once_with(curve_id, BLOCK_HASH)


@pytest.mark.unit
def test_has_contract_address_changed_returns_false_when_same(w3: Web3StakingModule):
    assert w3.staking_module.has_contract_address_changed() is False


@pytest.mark.unit
def test_has_contract_address_changed_returns_true_when_different(w3: Web3StakingModule):
    sm = w3.staking_module
    sm.module.accounting = Mock(return_value="0x" + "ab" * 20)

    assert sm.has_contract_address_changed() is True
    assert sm.has_contract_address_changed() is False


@pytest.mark.unit
def test_reload_contracts(w3: Web3StakingModule):
    sm = w3.staking_module
    original_module = sm.module
    original_oracle = sm.oracle

    sm.reload_contracts()

    assert sm.module is not original_module
    assert sm.oracle is not original_oracle
