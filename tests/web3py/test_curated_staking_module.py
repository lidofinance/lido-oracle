from unittest.mock import Mock

import pytest
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

from src import variables
from src.providers.execution.contracts.curated_staking_module import CuratedStakingModuleContract
from src.providers.execution.contracts.custom_fee_registry import CustomFeeRegistryContract
from src.providers.execution.contracts.meta_registry import MetaRegistryContract
from src.providers.execution.exceptions import InconsistentData
from src.types import NodeOperatorId
from src.web3py.extensions.curated_staking_module import CuratedModuleContracts
from src.web3py.extensions.staking_module import StakingModuleContracts
from tests.factory.blockstamp import ReferenceBlockStampFactory
from tests.factory.curated import HASH_A, HASH_B, NO_ID


MODULE = "0x" + "1" * 40
META_REGISTRY = "0x" + "2" * 40


def make_provider_address(index: int) -> str:
    return "0x" + f"{index:02x}" * 20


def make_registry(step=100, discount=0) -> Mock:
    registry = Mock(spec=CustomFeeRegistryContract)
    if isinstance(step, Exception):
        registry.fee_share_discount_step.side_effect = step
    else:
        registry.fee_share_discount_step.return_value = step
    registry.get_fee_share_discount.return_value = discount
    return registry


class CMHarness:
    """Wires `w3` so that contracts are resolved by address, like `w3.eth.contract` does."""

    def __init__(self, web3, monkeypatch, registries: list[Mock], consensus_version: int = 5):
        monkeypatch.setattr(variables, "STAKING_MODULE_ADDRESS", MODULE)
        monkeypatch.setattr(CuratedModuleContracts, "_load_contracts", lambda self: None)

        self.module = Mock(spec=CuratedStakingModuleContract)
        self.module.get_meta_registry_address.return_value = META_REGISTRY

        self.meta_registry = Mock(spec=MetaRegistryContract)
        self.meta_registry.get_weight_boost_providers.return_value = [
            make_provider_address(i) for i in range(1, len(registries) + 1)
        ]

        contracts = {
            MODULE: self.module,
            META_REGISTRY: self.meta_registry,
            **{make_provider_address(i): registry for i, registry in enumerate(registries, 1)},
        }
        self.contract_factory = Mock(side_effect=lambda address, **_: contracts[address])
        monkeypatch.setattr(web3.eth, "contract", self.contract_factory)

        web3.attach_modules({"staking_module": CuratedModuleContracts})
        self.staking_module: CuratedModuleContracts = web3.staking_module
        self.staking_module.module = Mock(address=MODULE)
        self.staking_module.oracle = Mock()
        self.staking_module.oracle.get_consensus_version.return_value = consensus_version


@pytest.mark.unit
class TestStakingModuleContractsGetFeeShareDiscount:
    def test_get_fee_share_discount__base_module__returns_zero_without_contract_reads(self, web3, monkeypatch):
        monkeypatch.setattr(variables, "STAKING_MODULE_ADDRESS", MODULE)
        monkeypatch.setattr(StakingModuleContracts, "_load_contracts", lambda self: None)
        contract_factory = Mock()
        monkeypatch.setattr(web3.eth, "contract", contract_factory)
        web3.attach_modules({"staking_module": StakingModuleContracts})
        staking_module = web3.staking_module
        staking_module.oracle = Mock()
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = staking_module.get_fee_share_discount(NO_ID, blockstamp)

        assert result == 0
        contract_factory.assert_not_called()
        staking_module.oracle.get_consensus_version.assert_not_called()


@pytest.mark.unit
class TestCuratedModuleContractsGetFeeShareDiscount:
    def test_get_fee_share_discount__consensus_version_below_activation__returns_zero_without_registry_reads(
        self, web3, monkeypatch
    ):
        harness = CMHarness(web3, monkeypatch, [make_registry(discount=5000)], consensus_version=4)
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

        assert result == 0
        harness.staking_module.oracle.get_consensus_version.assert_called_once_with(HASH_A)
        harness.contract_factory.assert_not_called()
        harness.meta_registry.get_weight_boost_providers.assert_not_called()

    def test_get_fee_share_discount__no_providers__returns_zero(self, web3, monkeypatch):
        harness = CMHarness(web3, monkeypatch, [])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

        assert result == 0
        harness.meta_registry.get_weight_boost_providers.assert_called_once_with(HASH_A)

    @pytest.mark.parametrize("discount", [0, 100, 5000, 10000])
    def test_get_fee_share_discount__single_match__returns_registry_discount(self, web3, monkeypatch, discount):
        registry = make_registry(discount=discount)
        harness = CMHarness(web3, monkeypatch, [registry])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

        assert result == discount
        harness.module.get_meta_registry_address.assert_called_once_with(HASH_A)
        registry.fee_share_discount_step.assert_called_once_with(HASH_A)
        registry.get_fee_share_discount.assert_called_once_with(NO_ID, HASH_A)

    @pytest.mark.parametrize("error", [ContractLogicError("execution reverted"), BadFunctionCallOutput("0x")])
    def test_get_fee_share_discount__other_providers_fail_probe__skips_them_and_uses_match(
        self, web3, monkeypatch, error
    ):
        other = make_registry(step=error)
        registry = make_registry(discount=5000)
        harness = CMHarness(web3, monkeypatch, [other, registry, make_registry(step=error)])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

        assert result == 5000
        other.get_fee_share_discount.assert_not_called()

    @pytest.mark.parametrize("step", [0, 1, 99, 101, 10000])
    def test_get_fee_share_discount__probe_returns_other_step__returns_zero(self, web3, monkeypatch, step):
        registry = make_registry(step=step, discount=5000)
        harness = CMHarness(web3, monkeypatch, [registry])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

        assert result == 0
        registry.get_fee_share_discount.assert_not_called()

    def test_get_fee_share_discount__two_matches__raises_inconsistent_data(self, web3, monkeypatch):
        harness = CMHarness(web3, monkeypatch, [make_registry(), make_registry()])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        with pytest.raises(InconsistentData, match="Multiple CustomFeeRegistry"):
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

    def test_get_fee_share_discount__probe_raises_unexpected_error__propagates(self, web3, monkeypatch):
        harness = CMHarness(web3, monkeypatch, [make_registry(step=ValueError("boom"))])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        with pytest.raises(ValueError, match="boom"):
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

    @pytest.mark.parametrize("error", [ContractLogicError("execution reverted"), BadFunctionCallOutput("0x")])
    def test_get_fee_share_discount__discount_read_fails__propagates(self, web3, monkeypatch, error):
        registry = make_registry()
        registry.get_fee_share_discount.side_effect = error
        harness = CMHarness(web3, monkeypatch, [registry])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        with pytest.raises(type(error)):
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

    @pytest.mark.parametrize("discount", [1, 50, 150, 10001, 10100, 20000])
    def test_get_fee_share_discount__invalid_discount__raises_inconsistent_data(self, web3, monkeypatch, discount):
        harness = CMHarness(web3, monkeypatch, [make_registry(discount=discount)])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        with pytest.raises(InconsistentData, match="Invalid fee share discount"):
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp)

    def test_get_fee_share_discount__several_operators_in_one_frame__discovers_registry_once(self, web3, monkeypatch):
        registry = make_registry()
        registry.get_fee_share_discount.side_effect = lambda no_id, _: no_id * 100
        harness = CMHarness(web3, monkeypatch, [registry])
        blockstamp = ReferenceBlockStampFactory.build(block_hash=HASH_A)

        result = [harness.staking_module.get_fee_share_discount(NodeOperatorId(i), blockstamp) for i in (1, 2, 3)]

        assert result == [100, 200, 300]
        harness.meta_registry.get_weight_boost_providers.assert_called_once_with(HASH_A)
        registry.fee_share_discount_step.assert_called_once_with(HASH_A)

    def test_get_fee_share_discount__frames_with_different_blocks__reads_state_at_each_frame_block(
        self, web3, monkeypatch
    ):
        registry_a = make_registry(discount=1000)
        registry_b = make_registry(discount=2000)
        harness = CMHarness(web3, monkeypatch, [registry_a, registry_b])
        providers = {HASH_A: [make_provider_address(1)], HASH_B: [make_provider_address(2)]}
        harness.meta_registry.get_weight_boost_providers.side_effect = lambda block_hash: providers[block_hash]
        blockstamp_a = ReferenceBlockStampFactory.build(block_hash=HASH_A)
        blockstamp_b = ReferenceBlockStampFactory.build(block_hash=HASH_B)

        result = [
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp_a),
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp_b),
        ]

        assert result == [1000, 2000]
        harness.meta_registry.get_weight_boost_providers.assert_any_call(HASH_A)
        harness.meta_registry.get_weight_boost_providers.assert_any_call(HASH_B)
        registry_a.get_fee_share_discount.assert_called_once_with(NO_ID, HASH_A)
        registry_b.get_fee_share_discount.assert_called_once_with(NO_ID, HASH_B)

    def test_get_fee_share_discount__registry_state_differs_between_frames__reads_discount_at_own_block(
        self, web3, monkeypatch
    ):
        registry = make_registry()
        registry.get_fee_share_discount.side_effect = lambda no_id, block_hash: 1000 if block_hash == HASH_A else 3000
        harness = CMHarness(web3, monkeypatch, [registry])
        blockstamp_a = ReferenceBlockStampFactory.build(block_hash=HASH_A)
        blockstamp_b = ReferenceBlockStampFactory.build(block_hash=HASH_B)

        result = [
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp_a),
            harness.staking_module.get_fee_share_discount(NO_ID, blockstamp_b),
        ]

        assert result == [1000, 3000]
        registry.get_fee_share_discount.assert_any_call(NO_ID, HASH_A)
        registry.get_fee_share_discount.assert_any_call(NO_ID, HASH_B)
        harness.meta_registry.get_weight_boost_providers.assert_any_call(HASH_A)
        harness.meta_registry.get_weight_boost_providers.assert_any_call(HASH_B)
