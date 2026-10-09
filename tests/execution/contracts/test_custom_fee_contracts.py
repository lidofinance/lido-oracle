from collections import namedtuple
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from eth_abi import encode
from eth_tester import EthereumTester
from eth_tester.backends.mock import MockBackend
from eth_typing import ChecksumAddress
from web3 import EthereumTesterProvider, Web3

from src.providers.execution.contracts.custom_fee_registry import CustomFeeRegistryContract
from src.providers.execution.contracts.meta_registry import (
    ExternalOperator,
    MetaRegistryContract,
    OperatorGroup,
    SubNodeOperator,
)
from src.types import NodeOperatorId
from src.web3py.contract_tweak import tweak_w3_contracts


ADDR = cast(ChecksumAddress, "0x" + "1" * 40)
PROVIDER_ADDR = cast(ChecksumAddress, "0x" + "2" * 40)

WeightBoostProviderEntry = namedtuple("WeightBoostProviderEntry", ["provider", "mode"])


def _mock_contract():
    m = MagicMock()
    m.address = ADDR
    return m


@pytest.fixture()
def real_w3():
    w3 = Web3(provider=EthereumTesterProvider(EthereumTester(backend=MockBackend())))
    tweak_w3_contracts(w3)
    return w3


def make_real_contract(w3, contract_class):
    return cast(
        contract_class,
        w3.eth.contract(address=ADDR, ContractFactoryClass=contract_class, decode_tuples=True),
    )


@pytest.mark.unit
class TestMetaRegistryWeightBoostProviders:
    def test_get_weight_boost_providers__providers_registered__returns_addresses_at_block(self):
        contract = _mock_contract()
        contract.functions.getWeightBoostProviders.return_value.call.return_value = [
            WeightBoostProviderEntry(PROVIDER_ADDR, 0),
            WeightBoostProviderEntry(ADDR, 1),
        ]

        result = MetaRegistryContract.get_weight_boost_providers(contract, block_identifier="0xabc")

        assert result == [PROVIDER_ADDR, ADDR]
        contract.functions.getWeightBoostProviders.return_value.call.assert_called_once_with(block_identifier="0xabc")


@pytest.mark.unit
class TestMetaRegistryAbi:
    def test_get_weight_boost_providers__abi_encoded_entries__decodes_addresses(self, real_w3):
        contract = make_real_contract(real_w3, MetaRegistryContract)
        encoded = encode(["(address,uint8)[]"], [[(PROVIDER_ADDR, 0), (ADDR, 1)]])

        with patch.object(real_w3.eth, "call", return_value=encoded):
            result = contract.get_weight_boost_providers(block_identifier="0xabc")

        assert result == [PROVIDER_ADDR, ADDR]

    def test_get_weight_boost_providers__abi_encoded_empty_array__returns_empty_list(self, real_w3):
        contract = make_real_contract(real_w3, MetaRegistryContract)

        with patch.object(real_w3.eth, "call", return_value=encode(["(address,uint8)[]"], [[]])):
            result = contract.get_weight_boost_providers(block_identifier="0xdef")

        assert result == []

    def test_get_operator_group__abi_encoded_group__decodes_into_dataclass(self, real_w3):
        contract = make_real_contract(real_w3, MetaRegistryContract)
        external = bytes([1, 2]) + (5).to_bytes(8, "big")
        encoded = encode(["(string,(uint64,uint16)[],(bytes)[])"], [("group", [(3, 5000)], [(external,)])])

        with patch.object(real_w3.eth, "call", return_value=encoded):
            result = contract.get_operator_group(1, block_identifier="0xabc")

        assert result == OperatorGroup(
            name="group",
            sub_node_operators=[SubNodeOperator(node_operator_id=NodeOperatorId(3), share=5000)],
            external_operators=[ExternalOperator(data=external)],
        )

    def test_get_all_groups__abi_encoded_groups__decodes_each_group(self, real_w3):
        contract = make_real_contract(real_w3, MetaRegistryContract)
        group = encode(["(string,(uint64,uint16)[],(bytes)[])"], [("g", [(3, 5000)], [])])
        responses = [encode(["uint256"], [2]), group, group]

        with patch.object(real_w3.eth, "call", side_effect=responses):
            result = contract.get_all_groups(block_identifier="0xabc0")

        assert [g.name for g in result] == ["g", "g"]
        assert all(g.sub_node_operators == [SubNodeOperator(NodeOperatorId(3), 5000)] for g in result)


@pytest.mark.unit
class TestCustomFeeRegistryContract:
    def test_get_fee_share_discount__operator_id__returns_stored_value_at_block(self):
        contract = _mock_contract()
        contract.functions.getFeeShareDiscount.return_value.call.return_value = 5000

        result = CustomFeeRegistryContract.get_fee_share_discount(contract, NodeOperatorId(7), block_identifier="0x01")

        assert result == 5000
        contract.functions.getFeeShareDiscount.assert_called_once_with(7)
        contract.functions.getFeeShareDiscount.return_value.call.assert_called_once_with(block_identifier="0x01")

    def test_fee_share_discount_step__called__returns_step_at_block(self):
        contract = _mock_contract()
        contract.functions.FEE_SHARE_DISCOUNT_STEP.return_value.call.return_value = 100

        result = CustomFeeRegistryContract.fee_share_discount_step(contract, block_identifier="0x02")

        assert result == 100
        contract.functions.FEE_SHARE_DISCOUNT_STEP.return_value.call.assert_called_once_with(block_identifier="0x02")

    def test_get_fee_share_discount__abi_encoded_uint__decodes_int(self, real_w3):
        contract = make_real_contract(real_w3, CustomFeeRegistryContract)

        with patch.object(real_w3.eth, "call", return_value=encode(["uint256"], [1200])):
            result = contract.get_fee_share_discount(NodeOperatorId(1), block_identifier="0x03")

        assert result == 1200

    def test_fee_share_discount_step__abi_encoded_uint__decodes_int(self, real_w3):
        contract = make_real_contract(real_w3, CustomFeeRegistryContract)

        with patch.object(real_w3.eth, "call", return_value=encode(["uint256"], [100])):
            result = contract.fee_share_discount_step(block_identifier="0x04")

        assert result == 100
