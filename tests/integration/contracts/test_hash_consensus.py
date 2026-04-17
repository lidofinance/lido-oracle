import pytest
from web3.contract.contract import ContractFunction

from modules.common.types import ChainConfig, CurrentFrame, FrameConfig
from tests.integration.contracts.contract_utils import check_contract, check_value_type, make_checker
from type_aliases import SlotNumber


@pytest.mark.mainnet
@pytest.mark.integration
def test_hash_consensus_contract(hash_consensus_contract, caplog):
    members, _ = hash_consensus_contract.get_members()
    assert members, "Expected at least one committee member on mainnet"
    member_address = members[0]
    caplog.clear()

    check_contract(
        hash_consensus_contract,
        [
            ('get_members', None, lambda r: check_value_type(r, tuple)),
            ('get_chain_config', None, make_checker(ChainConfig)),
            ('get_current_frame', None, make_checker(CurrentFrame)),
            ('get_initial_ref_slot', None, make_checker(SlotNumber)),
            ('get_frame_config', None, make_checker(FrameConfig)),
            ('get_consensus_state_for_member', (member_address,), lambda r: check_value_type(r, tuple)),
            ('submit_report', (0, b'\x00' * 32, 1), make_checker(ContractFunction)),
        ],
        caplog,
    )
