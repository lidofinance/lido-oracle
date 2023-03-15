import pytest

from src.modules.submodules.typings import FrameConfig, ChainConfig
from src.services.withdrawal import Withdrawal
from src.constants import SHARE_RATE_PRECISION_E27
from tests.factory.blockstamp import ReferenceBlockStampFactory


@pytest.fixture()
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=1675263480)


@pytest.fixture()
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture()
def past_blockstamp(web3, consensus_client):
    yield ReferenceBlockStampFactory.build()


@pytest.fixture()
def subject(
        web3,
        past_blockstamp,
        chain_config,
        frame_config,
        contracts,
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

    assert result == [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000, 12000, 12262]
