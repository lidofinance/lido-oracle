from unittest.mock import Mock

import pytest
from eth_typing import HexStr
from web3 import Web3

from src.providers.keys.client import KAPIInconsistentData
from src.providers.keys.onchain import ModuleKeys
from src.providers.keys.types import LidoKey
from src.types import NodeOperatorId, StakingModuleAddress
from src.web3py.extensions.onchain_keys import OnchainKeysModule
from tests.factory.blockstamp import ReferenceBlockStampFactory


MODULE_A = Web3.to_checksum_address('0x' + 'aa' * 20)
MODULE_B = Web3.to_checksum_address('0x' + 'bb' * 20)


def lido_key(module: str, operator_id: int, index: int, pubkey: str) -> LidoKey:
    return LidoKey(
        index=index,
        key=HexStr(pubkey),
        deposit_signature=HexStr('0x' + '22' * 96),
        operator_index=NodeOperatorId(operator_id),
        used=True,
        module_address=Web3.to_checksum_address(module),
    )


@pytest.mark.unit
class TestOnchainKeysModule:
    @pytest.fixture
    def subject(self, web3) -> OnchainKeysModule:
        module = OnchainKeysModule(web3)
        module.fetcher = Mock()
        return module

    def test_get_used_lido_keys__all_router_modules__returns_keys_of_every_module(self, subject, web3):
        # Arrange
        blockstamp = ReferenceBlockStampFactory.build()
        web3.lido_contracts.staking_router.get_staking_modules = Mock(
            return_value=[Mock(staking_module_address=MODULE_A), Mock(staking_module_address=MODULE_B)]
        )
        key_a = lido_key(MODULE_A, 0, 0, '0x' + '01' * 48)
        key_b = lido_key(MODULE_B, 3, 0, '0x' + '02' * 48)
        subject.fetcher.fetch_modules_keys.return_value = [
            ModuleKeys(MODULE_A, {NodeOperatorId(0): 1}, [key_a]),
            ModuleKeys(MODULE_B, {NodeOperatorId(3): 1}, [key_b]),
        ]

        # Act
        keys = subject.get_used_lido_keys(blockstamp)

        # Assert
        assert keys == [key_a, key_b]
        subject.fetcher.fetch_modules_keys.assert_called_once_with([MODULE_A, MODULE_B], blockstamp.block_hash)

    def test_get_used_lido_keys__same_key_in_two_modules__raises(self, subject, web3):
        blockstamp = ReferenceBlockStampFactory.build()
        web3.lido_contracts.staking_router.get_staking_modules = Mock(return_value=[])
        pubkey = '0x' + '01' * 48
        subject.fetcher.fetch_modules_keys.return_value = [
            ModuleKeys(MODULE_A, {NodeOperatorId(0): 1}, [lido_key(MODULE_A, 0, 0, pubkey)]),
            ModuleKeys(MODULE_B, {NodeOperatorId(0): 1}, [lido_key(MODULE_B, 0, 0, pubkey)]),
        ]

        with pytest.raises(KAPIInconsistentData, match='duplicated key'):
            subject.get_used_lido_keys(blockstamp)

    def test_get_used_module_operators_keys__module__returns_keys_api_shape(self, subject):
        # Arrange
        blockstamp = ReferenceBlockStampFactory.build()
        key = lido_key(MODULE_A, 1, 0, '0x' + '01' * 48)
        subject.fetcher.fetch_modules_keys.return_value = [
            ModuleKeys(MODULE_A, {NodeOperatorId(0): 0, NodeOperatorId(1): 1}, [key]),
        ]

        # Act
        result = subject.get_used_module_operators_keys(StakingModuleAddress(MODULE_A), blockstamp)

        # Assert
        assert result['keys'] == [key]
        assert result['module'] == {'stakingModuleAddress': MODULE_A}
        assert result['operators'] == [
            {'index': 0, 'moduleAddress': MODULE_A, 'usedSigningKeys': 0},
            {'index': 1, 'moduleAddress': MODULE_A, 'usedSigningKeys': 1},
        ]
        subject.fetcher.fetch_modules_keys.assert_called_once_with([MODULE_A], blockstamp.block_hash)
