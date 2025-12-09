import pytest
from eth_typing import BlockNumber
from web3.types import Timestamp

from src.modules.submodules.types import FrameConfig, ChainConfig
from src.services.withdrawal import Withdrawal
from src.constants import SHARE_RATE_PRECISION_E27
from src.types import ReferenceBlockStamp, SlotNumber, EpochNumber


def get_blockstamp_by_state(w3, state_id) -> ReferenceBlockStamp:
    root = w3.cc.get_block_root(state_id).root
    slot_details = w3.cc.get_block_details(root)

    return ReferenceBlockStamp(
        slot_number=SlotNumber(int(slot_details.message.slot)),
        state_root=slot_details.message.state_root,
        block_number=BlockNumber(int(slot_details.message.body.execution_payload.block_number)),
        block_hash=slot_details.message.body.execution_payload.block_hash,
        block_timestamp=Timestamp(slot_details.message.body.execution_payload.timestamp),
        ref_slot=SlotNumber(int(slot_details.message.slot)),
        ref_epoch=EpochNumber(int(int(slot_details.message.slot) / 12)),
    )


@pytest.fixture
def chain_config():
    return ChainConfig(slots_per_epoch=32, seconds_per_slot=12, genesis_time=1675263480)


@pytest.fixture
def frame_config():
    return FrameConfig(initial_epoch=0, epochs_per_frame=10, fast_lane_length_slots=0)


@pytest.fixture
def past_blockstamp(web3_integration):
    return get_blockstamp_by_state(web3_integration, 'finalized')


@pytest.fixture
def subject(web3_integration, past_blockstamp, chain_config, frame_config):
    return Withdrawal(web3_integration, past_blockstamp, chain_config, frame_config)


@pytest.mark.testnet
@pytest.mark.integration
def test_happy_path(subject, past_blockstamp):
    withdrawal_vault_balance = subject.w3.lido_contracts.get_withdrawal_balance(past_blockstamp)
    el_rewards_vault_balance = subject.w3.lido_contracts.get_el_vault_balance(past_blockstamp)

    expected_min_withdrawal_id = subject.w3.lido_contracts.withdrawal_queue_nft.get_last_finalized_request_id(
        past_blockstamp.block_hash
    )
    expected_max_withdrawal_id = subject.w3.lido_contracts.withdrawal_queue_nft.get_last_request_id(
        past_blockstamp.block_hash
    )

    results = subject.get_finalization_batches(
        False, SHARE_RATE_PRECISION_E27, withdrawal_vault_balance, el_rewards_vault_balance
    )

    for result in results:
        assert expected_min_withdrawal_id < result <= expected_max_withdrawal_id
