import pytest
from pathlib import Path

from src.modules.submodules.typings import FrameConfig, ChainConfig
from src.services.withdrawal import Withdrawal
from src.typings import ReferenceBlockStamp
from src.constants import SHARE_RATE_PRECISION_E27
from src.web3py.extensions import LidoContracts


@pytest.fixture()
def contracts_local(web3, provider):
    with provider.use_mock(Path('common/contracts-withdrawal.v2.json')):
        # First contracts deployment
        web3.attach_modules({
            'lido_contracts': LidoContracts,
        })

@pytest.fixture()
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=1675263480)


@pytest.fixture()
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture()
def past_blockstamp(web3, consensus_client):
    return ReferenceBlockStamp(
        state_root='0xb8517bb1cb4ca6bfadaa5732c24cec0c937db0faaba9806e166dcc0c8bc20160',
        slot_number=286752,
        block_hash='0x01483df91303d4b2b0f3e871e99abbb9c071325477050b6a4ac7377a9ef66ec6',
        block_number=274685,
        block_timestamp='1678704624',
        ref_slot=286752,
        ref_epoch=23896
    )


@pytest.fixture()
def subject(
        web3,
        past_blockstamp,
        chain_config,
        frame_config,
        contracts_local,
        keys_api_client,
        consensus_client
):
    return Withdrawal(web3, past_blockstamp, chain_config, frame_config)


def test_returns_none_if_no_unfinalized_requests(subject, past_blockstamp):
    withdrawal_vault_balance = subject.w3.lido_contracts.get_withdrawal_balance(past_blockstamp)
    el_rewards_vault_balance = subject.w3.lido_contracts.get_el_vault_balance(past_blockstamp)

    result = subject.get_finalization_batches(
        False,
        SHARE_RATE_PRECISION_E27,
        withdrawal_vault_balance,
        el_rewards_vault_balance
    )

    assert result == [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 12241]
