"""
Merkle tree building and encoding tests.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from eth_typing import BlockNumber, ChecksumAddress, HexAddress, HexStr
from web3.types import Timestamp, Wei

from src.modules.accounting.types import (
    VaultFeeMap,
    VaultReserveMap,
    VaultsMap,
    VaultTotalValueMap,
)
from src.modules.submodules.types import ChainConfig
from src.providers.ipfs import CID
from src.services.staking_vaults import (
    MERKLE_TREE_VAULTS_FILENAME,
    StakingVaultsService,
)
from src.types import BlockHash, EpochNumber, ReferenceBlockStamp, SlotNumber, StateRoot
from tests.modules.accounting.staking_vault.conftest import (
    VaultAddresses,
    VaultFeeFactory,
    VaultInfoFactory,
)


class TestBuildTreeData:
    """Tests for build_tree_data and merkle tree methods."""

    @pytest.mark.unit
    def test_build_tree_happy_path(self):
        """Test building tree data with valid inputs."""
        vault_address = ChecksumAddress(HexAddress(HexStr('0x1234567890abcdef1234567890abcdef12345678')))

        vault_info = VaultInfoFactory.build(
            vault=vault_address,
            liability_shares=2_880 * 10**18,
            max_liability_shares=2_880 * 10**18,
            in_out_delta=Wei(1_234_567_890_000_000_000),
        )

        vaults: VaultsMap = {vault_address: vault_info}
        total_value = 1_000_000_000_000_000_000
        vaults_total_values: VaultTotalValueMap = {vault_address: total_value}
        vault_fee = VaultFeeFactory.build(infra_fee=100, liquidity_fee=200, reservation_fee=300, prev_fee=400)
        vaults_fees: VaultFeeMap = {vault_address: vault_fee}
        slashing_reserve = 5_555
        vaults_slashing_reserve: VaultReserveMap = {vault_address: slashing_reserve}

        tree_data = StakingVaultsService.build_tree_data(
            vaults, vaults_total_values, vaults_fees, vaults_slashing_reserve
        )

        assert len(tree_data) == 1
        assert tree_data[0] == (
            vault_address,
            total_value,
            1_000,
            vault_info.liability_shares,
            vault_info.max_liability_shares,
            slashing_reserve,
        )

    @pytest.mark.unit
    def test_build_tree_missing_total_value_raises(self):
        """Test that missing total value raises ValueError."""
        vault_address = ChecksumAddress(HexAddress(HexStr('0x1234567890abcdef1234567890abcdef12345678')))
        vault_info = VaultInfoFactory.build(vault=vault_address)

        vaults: VaultsMap = {vault_address: vault_info}
        vaults_total_values = {ChecksumAddress(HexAddress(HexStr('0xanother_vault_address_rauses_errror'))): 1_000}

        with pytest.raises(ValueError, match=f'Vault {vault_address} is not in total_values'):
            StakingVaultsService.build_tree_data(vaults, vaults_total_values, {}, {})

    @pytest.mark.unit
    def test_build_tree_missing_vault_fees_raises(self):
        """Test that missing vault fees raises ValueError."""
        vault_address = ChecksumAddress(HexAddress(HexStr('0x1234567890abcdef1234567890abcdef12345678')))
        vault_info = VaultInfoFactory.build(vault=vault_address)

        vaults: VaultsMap = {vault_address: vault_info}
        vaults_total_values: VaultTotalValueMap = {vault_address: 1_000}
        vaults_fees: VaultFeeMap = {
            ChecksumAddress(HexAddress(HexStr('0xanother_vault_address_rauses_errror'))): VaultFeeFactory.build()
        }

        with pytest.raises(ValueError, match=f'Vault {vault_address} is not in vaults_fees'):
            StakingVaultsService.build_tree_data(vaults, vaults_total_values, vaults_fees, {vault_address: 0})


class TestTreeEncoder:
    """Tests for tree_encoder static method."""

    @pytest.mark.unit
    def test_encode_bytes(self):
        """Test encoding bytes to hex string."""
        result = StakingVaultsService.tree_encoder(b'\x12\x34')
        assert result == '0x1234'

    @pytest.mark.unit
    def test_encode_cid(self):
        """Test encoding CID to string."""
        cid = CID('cid12345')
        result = StakingVaultsService.tree_encoder(cid)
        assert result == 'cid12345'

    @pytest.mark.unit
    def test_encode_dataclass(self):
        """Test encoding dataclass to dict."""
        bs = ReferenceBlockStamp(
            state_root=StateRoot(HexStr('state_root')),
            slot_number=SlotNumber(123456),
            block_hash=BlockHash(HexStr('0xabc123')),
            block_number=BlockNumber(789654),
            block_timestamp=Timestamp(1234),
            ref_slot=SlotNumber(123450),
            ref_epoch=EpochNumber(123451),
        )

        result = StakingVaultsService.tree_encoder(bs)
        assert result == {
            'block_hash': '0xabc123',
            'block_number': 789654,
            'block_timestamp': 1234,
            'ref_epoch': 123451,
            'ref_slot': 123450,
            'slot_number': 123456,
            'state_root': 'state_root',
        }

    @pytest.mark.unit
    def test_encode_invalid_type_raises(self):
        """Test that unsupported types raise TypeError."""
        with pytest.raises(TypeError, match="Object of type <class 'int'> is not JSON serializable"):
            StakingVaultsService.tree_encoder(42)


class TestDumpedTreeAndPublish:
    """Tests for dump/publish helpers."""

    @pytest.fixture
    def basic_setup(self):
        vault_address = VaultAddresses.VAULT_0
        vault_info = VaultInfoFactory.build(
            vault=vault_address,
            liability_shares=1,
            max_liability_shares=1,
            in_out_delta=Wei(123),
        )
        vaults: VaultsMap = {vault_address: vault_info}
        vaults_total_values: VaultTotalValueMap = {vault_address: Wei(100)}
        vault_fee = VaultFeeFactory.build(infra_fee=10, liquidity_fee=20, reservation_fee=30, prev_fee=40)
        vaults_fees: VaultFeeMap = {vault_address: vault_fee}
        vaults_slashing_reserve: VaultReserveMap = {vault_address: 5}

        bs = ReferenceBlockStamp(
            state_root=StateRoot(HexStr('0xabc')),
            slot_number=SlotNumber(10),
            block_hash=BlockHash(HexStr('0xdef')),
            block_number=BlockNumber(99),
            block_timestamp=Timestamp(123456),
            ref_slot=SlotNumber(9),
            ref_epoch=EpochNumber(1),
        )

        return vaults, vaults_total_values, vaults_fees, vaults_slashing_reserve, bs

    @pytest.mark.unit
    def test_get_dumped_tree_contains_expected_fields(self, basic_setup):
        vaults, total_values, fees, reserves, bs = basic_setup
        tree = StakingVaultsService.get_merkle_tree(
            StakingVaultsService.build_tree_data(vaults, total_values, fees, reserves)
        )

        chain_config = ChainConfig(slots_per_epoch=1, seconds_per_slot=12, genesis_time=0)
        dumped = StakingVaultsService.get_dumped_tree(
            tree=tree,
            vaults=vaults,
            bs=bs,
            prev_tree_cid='prev',
            chain_config=chain_config,
            vaults_fee_map=fees,
        )

        value_entry = dumped['values'][0]['value']
        assert value_entry[0] == VaultAddresses.VAULT_0
        assert dumped['extraValues'][VaultAddresses.VAULT_0]['prevFee'] == str(fees[VaultAddresses.VAULT_0].prev_fee)
        assert dumped['blockHash'] == bs.block_hash

    @pytest.mark.unit
    def test_publish_tree_calls_ipfs_with_ascii_payload(self, basic_setup):
        vaults, total_values, fees, reserves, bs = basic_setup
        w3_mock = MagicMock()
        w3_mock.ipfs.publish.return_value = 'cid123'
        service = StakingVaultsService(w3_mock)

        tree = service.get_merkle_tree(StakingVaultsService.build_tree_data(vaults, total_values, fees, reserves))
        chain_config = ChainConfig(slots_per_epoch=1, seconds_per_slot=12, genesis_time=0)

        cid = service.publish_tree(
            tree=tree,
            vaults=vaults,
            bs=bs,
            prev_tree_cid='prev',
            chain_config=chain_config,
            vaults_fee_map=fees,
        )

        w3_mock.ipfs.publish.assert_called_once()
        args, kwargs = w3_mock.ipfs.publish.call_args
        assert args[1] == MERKLE_TREE_VAULTS_FILENAME
        # Ensure ascii encoding
        assert isinstance(args[0], bytes)
        args[0].decode('ascii')
        assert cid == 'cid123'

    @pytest.mark.unit
    def test_is_tree_root_valid_checks_root(self):
        tree_data = [
            (
                VaultAddresses.VAULT_0,
                Wei(100),
                10,
                1,
                1,
                0,
            )
        ]
        service = StakingVaultsService(MagicMock())
        merkle_tree = service.get_merkle_tree(tree_data)
        expected_root = f'0x{merkle_tree.root.hex()}'

        vault_record = SimpleNamespace(
            vault_address=VaultAddresses.VAULT_0,
            total_value_wei=Wei(100),
            fee=10,
            liability_shares=1,
            max_liability_shares=1,
            slashing_reserve=0,
        )
        report = SimpleNamespace(values=[vault_record], tree=[expected_root])

        assert service.is_tree_root_valid(expected_root, report)
        assert not service.is_tree_root_valid('0xdead', report)
