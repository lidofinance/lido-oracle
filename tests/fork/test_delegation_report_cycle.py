import logging
from contextlib import contextmanager

import pytest
from eth_account import Account
from web3 import Web3

from src.modules.common.types import FrameConfig
from src.modules.oracles.ejector.ejector import Ejector
from src.utils.range import sequence
from src.web3py.extensions.signer import SignerModule
from tests.fork.conftest import first_slot_of_epoch


logger = logging.getLogger('fork_tests')

# Deployed by the Lido team on Hoodi; deploy() mints a DelegationContract matching the current
# assets/DelegationContract.json interface (owner/execute/getDelegate/...).
DELEGATION_FACTORY_ADDRESS = Web3.to_checksum_address('0x76Af23C7e71004038BeE4a1ceba8c441f4cA239b')
DELEGATION_FACTORY_ABI = [
    {
        'type': 'function',
        'name': 'deploy',
        'inputs': [
            {'name': 'owner', 'type': 'address'},
            {'name': 'delegate', 'type': 'address'},
            {'name': 'cooldown', 'type': 'uint256'},
        ],
        'outputs': [{'name': '', 'type': 'address'}],
        'stateMutability': 'nonpayable',
    },
]

TOTAL_MEMBERS = 6
QUORUM = 5


@pytest.fixture()
def hash_consensus_bin():
    with open('tests/fork/contracts/lido/HashConsensus_bin') as f:
        yield f.read()


@pytest.fixture
def ejector_module(web3):
    yield Ejector(web3)


@pytest.fixture
def finalized_slots_after_ref_slot(frame_config: FrameConfig):
    # Lands inside the initial reporting frame, after its reference slot has already passed
    # but before any member has had a chance to submit a report for it.
    _from = frame_config.initial_epoch + 1
    _to = frame_config.initial_epoch + 2
    return [first_slot_of_epoch(i) for i in sequence(_from, _to)]


@pytest.fixture()
def delegation_owner_account(accounts_from_fork):
    addresses, _ = accounts_from_fork
    return addresses[TOTAL_MEMBERS]  # an anvil dev account outside the 6 committee seats


@pytest.fixture()
def delegate_account(accounts_from_fork):
    addresses, private_keys = accounts_from_fork
    return addresses[0], private_keys[0]


@pytest.fixture()
def fresh_delegation_contract(web3, delegation_owner_account, delegate_account):
    """Deploys a fresh DelegationContract via the Hoodi DelegationFactory and delegates it to
    `delegate_account` immediately (cooldown=0), i.e. the "create delegation contract" step."""
    delegate_address, _ = delegate_account

    factory = web3.eth.contract(address=DELEGATION_FACTORY_ADDRESS, abi=DELEGATION_FACTORY_ABI)
    deploy_call = factory.functions.deploy(delegation_owner_account, delegate_address, 0)

    # CREATE address only depends on the factory's nonce, which doesn't change between this
    # static call and the transaction right below - so this predicts the real deployed address.
    predicted_address = deploy_call.call({'from': delegation_owner_account})
    deploy_call.transact({'from': delegation_owner_account})

    delegation_address = Web3.to_checksum_address(predicted_address)
    logger.info(f"TESTRUN Deployed fresh DelegationContract at {delegation_address}")

    return delegation_address


@pytest.fixture()
def six_members_with_delegation(new_hash_consensus, accounts_from_fork, fresh_delegation_contract):
    """Sets up a 6-member committee, then replaces one plain EOA member with the delegation
    contract, ending at 6 members / quorum 5 (5-of-6)."""
    addresses, private_keys = accounts_from_fork

    DEFAULT_ADMIN_ROLE = "0x" + new_hash_consensus.functions.DEFAULT_ADMIN_ROLE().call().hex()
    MANAGE_MEMBERS_AND_QUORUM_ROLE = "0x" + new_hash_consensus.functions.MANAGE_MEMBERS_AND_QUORUM_ROLE().call().hex()
    admin = new_hash_consensus.functions.getRoleMember(DEFAULT_ADMIN_ROLE, 0).call()
    new_hash_consensus.functions.grantRole(MANAGE_MEMBERS_AND_QUORUM_ROLE, admin).transact({'from': admin})

    for i, address in enumerate(addresses[:TOTAL_MEMBERS]):
        new_hash_consensus.functions.addMember(address, i + 1).transact({'from': admin})

    # Replace the first plain member with the delegation contract, keeping 6 members / quorum 5.
    new_hash_consensus.functions.removeMember(addresses[0], TOTAL_MEMBERS - 1).transact({'from': admin})
    new_hash_consensus.functions.addMember(fresh_delegation_contract, QUORUM).transact({'from': admin})

    return [(addresses[i], private_keys[i]) for i in range(1, TOTAL_MEMBERS)]  # 5 plain EOA members


@pytest.fixture()
def granted_submit_role(report_contract, six_members_with_delegation, fresh_delegation_contract):
    """Grants SUBMIT_DATA_ROLE to every committee identity so the fast-lane offchain delay
    calculation short-circuits instead of sleeping through real 12s Hoodi slots."""
    DEFAULT_ADMIN_ROLE = "0x" + report_contract.functions.DEFAULT_ADMIN_ROLE().call().hex()
    oracle_admin = report_contract.functions.getRoleMember(DEFAULT_ADMIN_ROLE, 0).call()
    submit_role = report_contract.functions.SUBMIT_DATA_ROLE().call()

    for address, _ in six_members_with_delegation:
        report_contract.functions.grantRole(submit_role, address).transact({'from': oracle_admin})
    report_contract.functions.grantRole(submit_role, fresh_delegation_contract).transact({'from': oracle_admin})


@pytest.fixture()
def signer_from(web3):
    @contextmanager
    def _use(account, account_2, delegation_contract_address):
        web3.signer = SignerModule(web3, account, account_2, delegation_contract_address)
        yield

    return _use


@pytest.mark.testnet
@pytest.mark.fork
@pytest.mark.integration
@pytest.mark.parametrize('module', [ejector_module], indirect=True)
@pytest.mark.parametrize('running_finalized_slots', [finalized_slots_after_ref_slot], indirect=True)
class TestDelegatedMemberReportCycle:
    def test_cycle_handler__quorum_reached_via_delegated_member__submits_hash_then_data(
        self,
        module,
        six_members_with_delegation,
        fresh_delegation_contract,
        granted_submit_role,  # pylint: disable=unused-argument
        signer_from,
        running_finalized_slots,
        delegate_account,
    ):
        # Arrange
        assert module.report_contract.get_last_processing_ref_slot('latest') == 0

        switch_finalized, get_current_finalized = running_finalized_slots

        frame = module.get_initial_or_current_frame(module._receive_last_finalized_slot())  # pylint: disable=protected-access
        assert get_current_finalized() > frame.ref_slot, "Finalized slot must land after the frame's reference slot"

        consensus_contract = module._get_consensus_contract(module._get_latest_blockstamp())  # pylint: disable=protected-access
        any_member_address, _ = six_members_with_delegation[0]
        state_before = consensus_contract.get_consensus_state_for_member(any_member_address, 'latest')
        assert state_before.currentFrameConsensusReport == b'\x00' * 32, "No report should exist yet for this frame"

        _, delegate_private_key = delegate_account
        delegate_account_obj = Account.from_key(delegate_private_key)

        # Deliberately drive only 4 of the 5 plain EOA members (the 5th stays "offline"), so the
        # 5-of-6 quorum can only be reached with the delegated member's participation too.
        driven_plain_members = six_members_with_delegation[:4]

        # Act
        report_frame = frame
        while switch_finalized():
            for _, private_key in driven_plain_members:
                with signer_from(Account.from_key(private_key), None, None):
                    module.cycle_handler()
            with signer_from(None, delegate_account_obj, fresh_delegation_contract):
                module.cycle_handler()

            report_frame = module.get_initial_or_current_frame(
                module._receive_last_finalized_slot()  # pylint: disable=protected-access
            )

        # Assert
        state_after = consensus_contract.get_consensus_state_for_member(fresh_delegation_contract, 'latest')
        assert state_after.lastMemberReportRefSlot == report_frame.ref_slot, (
            "Delegated member's report hash was not registered by HashConsensus"
        )

        last_processing_ref_slot = module.report_contract.get_last_processing_ref_slot('latest')
        assert last_processing_ref_slot == report_frame.ref_slot, (
            "Report data was not submitted after quorum was reached"
        )
