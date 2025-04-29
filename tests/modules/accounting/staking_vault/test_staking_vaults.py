# test_my_class.py

from unittest.mock import MagicMock

import pytest
from eth_typing import ChecksumAddress, BlockNumber, HexAddress, HexStr
from web3.types import Timestamp

from src.main import ipfs_providers
from src.modules.accounting.staking_vaults import StakingVaults
from src.modules.accounting.types import VaultInfo, VaultData, VaultsData, VaultsMap
from src.providers.consensus.types import Validator, ValidatorState, PendingDeposit
from src.providers.ipfs import MultiIPFSProvider
from src.types import BlockStamp, ValidatorIndex, Gwei, EpochNumber, SlotNumber, BlockHash, StateRoot


class TestStakingVaults:
    ipfs_client: MultiIPFSProvider
    staking_vaults: StakingVaults

    def setup_method(self):
        self.ipfs_client = MultiIPFSProvider(ipfs_providers(), retries=3)

        # Vault addresses
        vault_adr_0 = ChecksumAddress(HexAddress(HexStr('0xE312f1ed35c4dBd010A332118baAD69d45A0E302')))
        vault_adr_1 = ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC')))
        vault_adr_2 = ChecksumAddress(HexAddress(HexStr('0x20d34FD0482E3BdC944952D0277A306860be0014')))
        vault_adr_3 = ChecksumAddress(HexAddress(HexStr('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4')))

        # --- VaultHub Mock ---
        vault_hub_mock = MagicMock()
        vault_hub_mock.get_all_vaults.return_value = [
            VaultInfo(
                vault=vault_adr_0,
                balance=1000000000000000000,
                in_out_delta=1000000000000000000,
                withdrawal_credentials='0x020000000000000000000000e312f1ed35c4dbd010a332118baad69d45a0e302',
                liability_shares=0,
            ),
            VaultInfo(
                vault=vault_adr_1,
                balance=0,
                in_out_delta=2000000000000000000,
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                liability_shares=490000000000000000,
            ),
            VaultInfo(
                vault=vault_adr_2,
                balance=2000900000000000000,
                in_out_delta=2000900000000000000,
                withdrawal_credentials='0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014',
                liability_shares=1200000000000010001,
            ),
            VaultInfo(
                vault=vault_adr_3,
                balance=1000000000000000000,
                in_out_delta=1000000000000000000,
                withdrawal_credentials='0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4',
                liability_shares=0,
            ),
        ]

        # --- ConsensusClient Mock ---
        cc_mock = MagicMock()
        cc_mock.get_pending_deposits.return_value = []

        # --- Web3 Mock ---
        w3_mock = MagicMock()

        self.staking_vaults = StakingVaults(w3_mock, cc_mock, self.ipfs_client, vault_hub_mock)

    @pytest.mark.unit
    def test_manual_vault_report(self):
        bs = BlockStamp(
            state_root=StateRoot(HexStr('0xcdbb26ef98f4f6c46262f34e980dcc92c28268ba6ca9b7d45668eb0c23cad3c3')),
            slot_number=SlotNumber(7314880),
            block_hash=BlockHash(HexStr('0xbb3ba9405346f2448e9fa02b110539dde714e6e3f06bd5207dc29e14db353a3a')),
            block_number=BlockNumber(8027890),
            block_timestamp=Timestamp(1743512160),
        )

        validators: list[Validator] = [
            Validator(
                index=ValidatorIndex(1985),
                balance=Gwei(32834904184),
                validator=ValidatorState(
                    pubkey='0x862d53d9e4313374d202f2b28e6ffe64efb0312f9c2663f2eef67b72345faa8932b27f9b9bb7b476d9b5e418fea99124',
                    withdrawal_credentials='0x020000000000000000000000e312f1ed35c4dbd010a332118baad69d45a0e302',
                    effective_balance=Gwei(32000000000),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(225469),
                    activation_epoch=EpochNumber(225475),
                    exit_epoch=EpochNumber(18446744073709551615),
                    withdrawable_epoch=EpochNumber(18446744073709551615),
                ),
            ),
            Validator(
                index=ValidatorIndex(1986),
                balance=Gwei(40000000000),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
            Validator(
                index=ValidatorIndex(1987),
                balance=Gwei(50000000000),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
            Validator(
                index=ValidatorIndex(1987),
                balance=Gwei(60000000000),
                validator=ValidatorState(
                    pubkey='0xa5d9411ef615c74c9240634905d5ddd46dc40a87a09e8cc0332afddb246d291303e452a850917eefe09b3b8c70a307ce',
                    withdrawal_credentials='0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4',
                    effective_balance=Gwei(0),
                    slashed=False,
                    activation_eligibility_epoch=EpochNumber(226130),
                    activation_epoch=EpochNumber(226136),
                    exit_epoch=EpochNumber(227556),
                    withdrawable_epoch=EpochNumber(227812),
                ),
            ),
        ]

        pending_deposits: list[PendingDeposit] = [
            # Valid
            PendingDeposit(
                pubkey='0xa50a7821c793e80710f51c681b28f996e5c2f1fa00318dbf91b5844822d58ac2fef892b79aea386a3b97829e090a393e',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xb5b222b452892bd62a7d2b4925e15bf9823c4443313d86d3e1fe549c86aa8919d0cdd1d5b60d9d3184f3966ced21699f124a14a0d8c1f1ae3e9f25715f40c3e7b81a909424c60ca7a8cbd79f101d6bd86ce1bdd39701cf93b2eecce10699f40b',
                slot=SlotNumber(259388),
            ),
            # Invalid
            PendingDeposit(
                pubkey='0x8c96ad1b9a1acf4a898009d96293d191ab911b535cd1e6618e76897b5fa239a7078f1fbf9de8dd07a61a51b137c74a87',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0x978f286178050a3dbf6f8551b8020f72dd1de8223fc9cb8553d5ebb22f71164f4278d9b970467084a9dcd54ad07ec8d60792104ff82887b499346f3e8adc55a86f26bfbb032ac2524da42d5186c5a8ed0ccf9d98e9f6ff012cfafbd712335aa5',
                slot=SlotNumber(259654),
            ),
            # Invalid
            PendingDeposit(
                pubkey='0x99eeb66e77fef5c71d3b303774ecded0d52d521e8d665c2d0f350c33f5f82e7ddd88dd9bc4f8014fb22820beda3a8a85',
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
                amount=Gwei(1000000000),
                signature='0xb4ea337eb8d0fc47361672d4a153dbe3cd943a0418c9f1bc586bca95cdcf8615d60a2394b7680276c4597a2524f9bcf1088c40a08902841ff68d508a9f825803b9fac3bc6333cf3afa7503f560ccf6f689be5b0f5d08fa9e21cb203aa1f53259',
                slot=SlotNumber(260393),
            ),
        ]

        tree_data, vault_data = self.staking_vaults.get_vaults_data(validators, pending_deposits, bs)
        merkle_tree = self.staking_vaults.get_merkle_tree(tree_data)
        got = f"0x{merkle_tree.root.hex()}"
        expected = '0x3dc48700af87f44fd9486bf0dcb88a35b0b1f2087af8922384e5153eee46837e'
        assert got == expected
        assert len(merkle_tree.root) == 32

        # (address, total_value, in_out_delta, fees, liability_shares)
        expected_tree_data = [
            ('0xE312f1ed35c4dBd010A332118baAD69d45A0E302', 33834904184000000000, 1000000000000000000, 0, 0),
            (
                '0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC',
                41000000000000000000,
                2000000000000000000,
                0,
                490000000000000000,
            ),
            (
                '0x20d34FD0482E3BdC944952D0277A306860be0014',
                52000900000000000000,
                2000900000000000000,
                0,
                1200000000000010001,
            ),
            ('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4', 61000000000000000000, 1000000000000000000, 0, 0),
        ]

        assert expected_tree_data == tree_data

        expected_vaults_data: VaultsMap = {
            ChecksumAddress(HexAddress(HexStr('0xE312f1ed35c4dBd010A332118baAD69d45A0E302'))): VaultData(
                vault_ind=0,
                balance_wei=1000000000000000000,
                in_out_delta=1000000000000000000,
                liability_shares=0,
                fee=0,
                address=ChecksumAddress(HexAddress(HexStr('0xE312f1ed35c4dBd010A332118baAD69d45A0E302'))),
                withdrawal_credentials='0x020000000000000000000000e312f1ed35c4dbd010a332118baad69d45a0e302',
            ),
            ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC'))): VaultData(
                vault_ind=1,
                balance_wei=0,
                in_out_delta=2000000000000000000,
                liability_shares=490000000000000000,
                fee=0,
                address=ChecksumAddress(HexAddress(HexStr('0x652b70E0Ae932896035d553fEaA02f37Ab34f7DC'))),
                withdrawal_credentials='0x020000000000000000000000652b70e0ae932896035d553feaa02f37ab34f7dc',
            ),
            ChecksumAddress(HexAddress(HexStr('0x20d34FD0482E3BdC944952D0277A306860be0014'))): VaultData(
                vault_ind=2,
                balance_wei=2000900000000000000,
                in_out_delta=2000900000000000000,
                liability_shares=1200000000000010001,
                fee=0,
                address=ChecksumAddress(HexAddress(HexStr('0x20d34FD0482E3BdC944952D0277A306860be0014'))),
                withdrawal_credentials='0x02000000000000000000000020d34fd0482e3bdc944952d0277a306860be0014',
            ),
            ChecksumAddress(HexAddress(HexStr('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4'))): VaultData(
                vault_ind=3,
                balance_wei=1000000000000000000,
                in_out_delta=1000000000000000000,
                liability_shares=0,
                fee=0,
                address=ChecksumAddress(HexAddress(HexStr('0x60B614c42d92d6c2E68AF7f4b741867648aBf9A4'))),
                withdrawal_credentials='0x02000000000000000000000060b614c42d92d6c2e68af7f4b741867648abf9a4',
            ),
        }

        assert expected_vaults_data == vault_data

        # proof_cid = self.StakingVaults.publish_proofs(merkle_tree, bs, vaults)
        # print(proof_cid)

        # proof_tree = self.StakingVaults.publish_tree(merkle_tree, bs, "2312")
        # print(proof_tree)

        # got = f"0x{merkle_tree.root.hex()}"
        # expected = '0xd832e823b84db9ba0d7ba52b3647953c65ae0f86b81949a31605492ebe46f93a'
        # assert got == expected
