from unittest.mock import Mock

import pytest

from src.modules.submodules.typings import ChainConfig
from src.providers.consensus.typings import Validator, ValidatorStatus, ValidatorState
from src.services.bunker import BunkerService, BunkerConfig
from src.providers.keys.typings import LidoKey
from src.services.bunker_cases.abnormal_cl_rebase import AbnormalClRebase
from src.typings import BlockNumber, BlockStamp, ReferenceBlockStamp


def simple_blockstamp(block_number: int, state_root: str) -> BlockStamp:
    return ReferenceBlockStamp('', state_root, block_number, '', block_number, 0, block_number, block_number)


def simple_key(pubkey: str) -> LidoKey:
    key = object.__new__(LidoKey)
    key.key = pubkey
    return key


def simple_validator(index, pubkey, balance, slashed=False, withdrawable_epoch='') -> Validator:
    return Validator(
        index=str(index),
        balance=str(balance),
        status=ValidatorStatus.ACTIVE_ONGOING,
        validator=ValidatorState(
            pubkey=pubkey,
            withdrawal_credentials='',
            effective_balance=str(32 * 10 ** 9),
            slashed=slashed,
            activation_eligibility_epoch='',
            activation_epoch='0',
            exit_epoch='100500',
            withdrawable_epoch=withdrawable_epoch,
        )
    )


@pytest.fixture
def mock_get_first_non_missed_slot(monkeypatch):

    def _get_first_non_missed_slot(_, ref_slot, last_finalized_slot_number, ref_epoch):

        slots = {
            0: simple_blockstamp(0, '0x0'),
            10: simple_blockstamp(10, '0x10'),
            20: simple_blockstamp(20, '0x20'),
            30: simple_blockstamp(30, '0x30'),
        }

        return slots[ref_slot]

    monkeypatch.setattr(
        'src.services.bunker_cases.abnormal_cl_rebase.get_first_non_missed_slot', Mock(side_effect=_get_first_non_missed_slot)
    )


@pytest.fixture
def mock_get_eth_distributed_events(abnormal_case):

    def _get_eth_distributed_events(from_block: BlockNumber, to_block: BlockNumber):
        events = {
            (1, 10): [{'args': {'withdrawalsWithdrawn': 1 * 10 ** 18}}],
            (1, 20): [{'args': {'withdrawalsWithdrawn': 1 * 10 ** 18}}],
            (11, 20): [],
            (21, 30): [{'args': {'withdrawalsWithdrawn': 7 * 10 ** 18}}, {'args': {'withdrawalsWithdrawn': 5 * 10 ** 18}}],
            (21, 40): [{'args': {'withdrawalsWithdrawn': 12 * 10 ** 18}}],
            (31, 40): [],
        }
        return events[(from_block, to_block)]

    abnormal_case._get_eth_distributed_events = Mock(side_effect=_get_eth_distributed_events)


@pytest.fixture
def mock_get_total_supply(bunker):

    def _get_total_supply(block: BlockStamp):

        supplies = {
            0: 15 * 10 ** 18,
        }

        return supplies[block.block_number]

    bunker._get_total_supply = Mock(side_effect=_get_total_supply)


@pytest.fixture
def mock_get_withdrawal_vault_balance(abnormal_case, contracts):
    def _get_withdrawal_vault_balance(blockstamp: BlockStamp):
        balance = {
            0: 15 * 10 ** 18,
            10: 14 * 10 ** 18,
            20: 14 * 10 ** 18,
            30: 2 * 10 ** 18,
            40: 2 * 10 ** 18,
        }
        return balance[blockstamp.block_number]

    abnormal_case.w3.lido_contracts.get_withdrawal_balance = Mock(side_effect=_get_withdrawal_vault_balance)


@pytest.fixture
def mock_get_validators(web3):

    def _get_validators(state: ReferenceBlockStamp, _=None):
        validators = {
            0: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', 32 * 10 ** 9),
                simple_validator(4, '0x04', 32 * 10 ** 9),
                simple_validator(5, '0x05', 32 * 10 ** 9),
            ],
            10: [
                simple_validator(0, '0x00', 15 + 32 * 10 ** 9),
                simple_validator(1, '0x01', 17 + 32 * 10 ** 9),
                simple_validator(2, '0x02', 63 + 32 * 10 ** 9),
                simple_validator(3, '0x03', (32 * 10 ** 9) + 1),
                simple_validator(4, '0x04', 32 * 10 ** 9),
                simple_validator(5, '0x05', (32 * 10 ** 9) + 99),
            ],
            20: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', (32 * 10 ** 9) - 200),
                simple_validator(4, '0x04', 0),
                simple_validator(5, '0x05', (32 * 10 ** 9) - 100500),
            ],
            30: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', 32 * 10 ** 9),
                simple_validator(4, '0x04', 32 * 10 ** 9),
            ],
            40: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', (32 * 10 ** 9) + 333333),
                simple_validator(4, '0x04', 32 * 10 ** 9),
                simple_validator(5, '0x05', (32 * 10 ** 9) + 824112),
            ],
            1000: [
                simple_validator(0, '0x00', 32 * 10 ** 9),
                simple_validator(1, '0x01', 32 * 10 ** 9),
                simple_validator(2, '0x02', 32 * 10 ** 9),
                simple_validator(3, '0x03', 32 * 10 ** 9, slashed=True, withdrawable_epoch='10001'),
                simple_validator(4, '0x04', 32 * 10 ** 9, slashed=True, withdrawable_epoch='10001'),
                simple_validator(5, '0x05', 32 * 10 ** 9, slashed=True, withdrawable_epoch='10001'),
                *[simple_validator(i, f'0x0{i}', 32 * 10 ** 9) for i in range(6, 200)],
            ]
        }
        return validators[state.slot_number]

    web3.cc.get_validators_no_cache = Mock(side_effect=_get_validators)


@pytest.fixture
def bunker(web3, lido_validators) -> BunkerService:
    """Minimal initialized bunker service"""
    service = BunkerService(web3)
    return service


@pytest.fixture
def blockstamp():
    return simple_blockstamp(10, '0x10')


@pytest.fixture
def abnormal_case(web3, lido_validators, mock_get_validators, blockstamp) -> AbnormalClRebase:
    last_report_ref_slot = 0
    c_conf = ChainConfig(
        slots_per_epoch=1,
        seconds_per_slot=12,
        genesis_time=0,
    )
    b_conf = BunkerConfig(
        normalized_cl_reward_per_epoch=64,
        normalized_cl_reward_mistake_rate=0.1,
        rebase_check_nearest_epoch_distance=4,
        rebase_check_distant_epoch_distance=25
    )
    all_validators = {
        v.validator.pubkey: v for v in web3.cc.get_validators(blockstamp)
    }
    lido_validators = {
        v.validator.pubkey: v for v in web3.cc.get_validators(blockstamp)[3:6]
    }
    lido_keys = {
        '0x03': simple_key('0x03'),
        '0x04': simple_key('0x04'),
        '0x05': simple_key('0x05'),
    }
    return AbnormalClRebase(web3, b_conf, c_conf, last_report_ref_slot, all_validators, lido_keys, lido_validators)
