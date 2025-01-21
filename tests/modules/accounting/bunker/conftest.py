from unittest.mock import Mock

import pytest

from src.modules.submodules.types import ChainConfig
from src.providers.consensus.types import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerService
from src.providers.keys.types import LidoKey
from src.services.bunker_cases.abnormal_cl_rebase import AbnormalClRebase
from src.services.bunker_cases.types import BunkerConfig
from src.types import BlockNumber, BlockStamp, ReferenceBlockStamp
from tests.modules.ejector.test_exit_order_state_service import FAR_FUTURE_EPOCH


def simple_ref_blockstamp(block_number: int) -> ReferenceBlockStamp:
    return ReferenceBlockStamp(f"0x{block_number}", block_number, '', block_number, 0, block_number, block_number)


def simple_blockstamp(block_number: int) -> BlockStamp:
    return BlockStamp(f"0x{block_number}", block_number, '', block_number, 0)


def simple_key(pubkey: str) -> LidoKey:
    key = object.__new__(LidoKey)
    key.key = pubkey
    return key


def simple_validator(
    index, pubkey, balance, slashed=False, withdrawable_epoch='', exit_epoch='100500', activation_epoch="0"
) -> Validator:
    return Validator(
        index=str(index),
        balance=str(balance),
        validator=ValidatorState(
            pubkey=pubkey,
            withdrawal_credentials='',
            effective_balance=str(32 * 10**9),
            slashed=slashed,
            activation_eligibility_epoch='',
            activation_epoch=activation_epoch,
            exit_epoch=exit_epoch,
            withdrawable_epoch=withdrawable_epoch,
        ),
    )


@pytest.fixture
def mock_get_accounting_last_processing_ref_slot(abnormal_case):
    def _get_accounting_last_processing_ref_slot(blockstamp: ReferenceBlockStamp):
        return 10

    abnormal_case.w3.lido_contracts.get_accounting_last_processing_ref_slot = Mock(
        side_effect=_get_accounting_last_processing_ref_slot
    )


@pytest.fixture
def mock_get_used_lido_keys(abnormal_case):
    def _get_used_lido_keys(blockstamp: ReferenceBlockStamp):
        return [
            simple_key('0x03'),
            simple_key('0x04'),
            simple_key('0x05'),
        ]

    abnormal_case.w3.kac.get_used_lido_keys = Mock(side_effect=_get_used_lido_keys)


@pytest.fixture
def mock_get_blockstamp(monkeypatch):
    def _get_blockstamp(_, ref_slot, last_finalized_slot_number):
        slots = {
            0: simple_blockstamp(0),
            10: simple_blockstamp(10),
            20: simple_blockstamp(20),
            30: simple_blockstamp(30),
            31: simple_blockstamp(31),
            444424: simple_blockstamp(444420),
            444434: simple_blockstamp(444431),
            444444: simple_blockstamp(444444),
        }
        return slots[ref_slot]

    def _get_reference_blockstamp(_, ref_slot, last_finalized_slot_number, ref_epoch):
        slots = {
            0: simple_ref_blockstamp(0),
            10: simple_ref_blockstamp(10),
            20: simple_ref_blockstamp(20),
            30: simple_ref_blockstamp(30),
            33: simple_ref_blockstamp(33),
            444424: simple_ref_blockstamp(444420),
            444434: simple_ref_blockstamp(444431),
            444444: simple_ref_blockstamp(444444),
        }
        return slots[ref_slot]

    monkeypatch.setattr(
        'src.services.bunker_cases.abnormal_cl_rebase.get_blockstamp', Mock(side_effect=_get_blockstamp)
    )
    monkeypatch.setattr(
        'src.services.bunker_cases.abnormal_cl_rebase.get_reference_blockstamp',
        Mock(side_effect=_get_reference_blockstamp),
    )


@pytest.fixture
def mock_get_eth_distributed_events(abnormal_case):
    def _get_eth_distributed_events(from_block: BlockNumber, to_block: BlockNumber):
        events = {
            (1, 10): [{'args': {'withdrawalsWithdrawn': 1 * 10**18}}],
            (1, 20): [{'args': {'withdrawalsWithdrawn': 1 * 10**18}}],
            (11, 20): [],
            (21, 30): [
                {'args': {'withdrawalsWithdrawn': 7 * 10**18}},
                {'args': {'withdrawalsWithdrawn': 5 * 10**18}},
            ],
            (21, 40): [{'args': {'withdrawalsWithdrawn': 12 * 10**18}}],
            (31, 40): [],
            (32, 33): [],
            (1, 33): [],
        }
        return events[(from_block, to_block)]

    abnormal_case._get_eth_distributed_events = Mock(side_effect=_get_eth_distributed_events)


@pytest.fixture
def mock_get_withdrawal_vault_balance(abnormal_case, contracts):
    def _get_withdrawal_vault_balance(blockstamp: BlockStamp):
        balance = {
            0: 15 * 10**18,
            10: 14 * 10**18,
            20: 14 * 10**18,
            30: 2 * 10**18,
            31: 2 * 10**18,
            33: 2 * 10**18,
            40: 2 * 10**18,
            50: 2 * 10**18,
        }
        return balance[blockstamp.block_number]

    abnormal_case.w3.lido_contracts.get_withdrawal_balance_no_cache = Mock(side_effect=_get_withdrawal_vault_balance)


@pytest.fixture
def mock_get_validators(web3):
    def _get_validators(state: ReferenceBlockStamp, _=None):
        validators = {
            0: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', 32 * 10**9),
                simple_validator(4, '0x04', 32 * 10**9),
                simple_validator(5, '0x05', 32 * 10**9),
            ],
            10: [
                simple_validator(0, '0x00', 15 + 32 * 10**9),
                simple_validator(1, '0x01', 17 + 32 * 10**9),
                simple_validator(2, '0x02', 63 + 32 * 10**9),
                simple_validator(3, '0x03', (32 * 10**9) + 1),
                simple_validator(4, '0x04', 32 * 10**9),
                simple_validator(5, '0x05', (32 * 10**9) + 99),
            ],
            20: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', (32 * 10**9) - 200),
                simple_validator(4, '0x04', 0),
                simple_validator(5, '0x05', (32 * 10**9) - 100500),
            ],
            30: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', 32 * 10**9),
                simple_validator(4, '0x04', 32 * 10**9),
            ],
            31: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', 32 * 10**9),
                simple_validator(4, '0x04', 32 * 10**9),
                simple_validator(5, '0x05', 32 * 10**9),
            ],
            33: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', 32 * 10**9),
                simple_validator(4, '0x04', 32 * 10**9),
                simple_validator(5, '0x05', 32 * 10**9),
            ],
            40: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', (32 * 10**9) + 333333),
                simple_validator(4, '0x04', 32 * 10**9),
                simple_validator(5, '0x05', (32 * 10**9) + 824112),
            ],
            50: [
                simple_validator(4, '0x00', balance=0, activation_epoch=FAR_FUTURE_EPOCH),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', (32 * 10**9) + 333333),
                simple_validator(4, '0x04', balance=0, activation_epoch=FAR_FUTURE_EPOCH),
                simple_validator(5, '0x05', (32 * 10**9) + 824112),
            ],
            1000: [
                simple_validator(0, '0x00', 32 * 10**9),
                simple_validator(1, '0x01', 32 * 10**9),
                simple_validator(2, '0x02', 32 * 10**9),
                simple_validator(3, '0x03', 32 * 10**9, slashed=True, withdrawable_epoch='10001'),
                simple_validator(4, '0x04', 32 * 10**9, slashed=True, withdrawable_epoch='10001'),
                simple_validator(5, '0x05', 32 * 10**9, slashed=True, withdrawable_epoch='10001'),
                *[simple_validator(i, f'0x0{i}', 32 * 10**9) for i in range(6, 200)],
            ],
            123: [
                simple_validator(0, '0x00', 32 * 10**9, exit_epoch='1'),
                simple_validator(1, '0x01', 32 * 10**9, exit_epoch='1'),
                simple_validator(2, '0x02', 32 * 10**9, exit_epoch='1'),
                simple_validator(3, '0x03', 32 * 10**9, exit_epoch='1'),
                simple_validator(4, '0x04', 32 * 10**9, exit_epoch='1'),
                simple_validator(5, '0x05', 32 * 10**9, exit_epoch='1'),
            ],
        }
        return validators[state.slot_number]

    web3.cc.get_validators_no_cache = Mock(side_effect=_get_validators)
    web3.cc.get_validators = Mock(side_effect=_get_validators)


@pytest.fixture
def bunker(web3, lido_validators) -> BunkerService:
    """Minimal initialized bunker service"""
    service = BunkerService(web3)
    return service


@pytest.fixture
def blockstamp():
    return simple_ref_blockstamp(10)


@pytest.fixture
def abnormal_case(web3, lido_validators, contracts, mock_get_validators, blockstamp) -> AbnormalClRebase:
    c_conf = ChainConfig(
        slots_per_epoch=1,
        seconds_per_slot=12,
        genesis_time=0,
    )
    b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=4,
        rebase_check_distant_epoch_distance=25,
    )
    return AbnormalClRebase(web3, c_conf, b_conf)
