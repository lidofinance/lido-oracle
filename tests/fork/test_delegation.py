import pytest
from eth_account import Account
from web3 import Web3

from src import variables
from src.providers.execution.contracts.delegation_contract import DelegationContract
from src.providers.execution.contracts.hash_consensus import HashConsensusContract
from src.web3py.extensions.delegation import DelegationModule


@pytest.fixture()
def blockstamp_for_forking():
    return None


@pytest.fixture()
def finalized_slots(real_finalized_slot):
    return [real_finalized_slot]


@pytest.fixture()
def delegatee_account(accounts_from_fork, monkeypatch):
    addresses, private_keys = accounts_from_fork
    account = Account.from_key(private_keys[1])
    monkeypatch.setattr(variables, 'ACCOUNT', account)
    return addresses[1], private_keys[1]


@pytest.fixture()
def delegation_address():
    return Web3.to_checksum_address(variables.DELEGATION_CONTRACT_ADDRESS)


@pytest.fixture()
def web3_with_delegation(web3, delegatee_account, delegation_address, monkeypatch):
    delegatee_address, _ = delegatee_account

    web3.provider.make_request('anvil_setBalance', [delegatee_address, hex(10**18)])

    delegation_contract = web3.eth.contract(
        address=delegation_address,
        abi=DelegationContract.load_abi(DelegationContract.abi_path),
    )

    current_admin = delegation_contract.functions.admin().call()
    web3.provider.make_request('anvil_impersonateAccount', [current_admin])
    web3.provider.make_request('anvil_setBalance', [current_admin, hex(10**18)])

    delegation_contract.functions.assignDelegate(delegatee_address).transact({'from': current_admin})

    delegation_module = DelegationModule(web3, delegation_address)
    web3.attach_modules({'delegation': lambda: delegation_module})

    monkeypatch.setattr(variables, 'DAEMON', True)

    return web3


@pytest.fixture()
def hash_consensus_with_delegation_member(web3_with_delegation, delegation_address):
    consensus_address = web3_with_delegation.lido_contracts.accounting_oracle.functions.getConsensusContract().call()
    hash_consensus = web3_with_delegation.eth.contract(
        address=consensus_address,
        abi=HashConsensusContract.load_abi(HashConsensusContract.abi_path),
        decode_tuples=True,
    )

    consensus_admin_role = hash_consensus.functions.DEFAULT_ADMIN_ROLE().call()
    consensus_admin = hash_consensus.functions.getRoleMember(consensus_admin_role, 0).call()
    web3_with_delegation.provider.make_request('anvil_impersonateAccount', [consensus_admin])
    web3_with_delegation.provider.make_request('anvil_setBalance', [consensus_admin, hex(10**18)])

    manage_role = hash_consensus.functions.MANAGE_MEMBERS_AND_QUORUM_ROLE().call()
    hash_consensus.functions.grantRole(manage_role, consensus_admin).transact({'from': consensus_admin})

    current_quorum = hash_consensus.functions.getQuorum().call()
    hash_consensus.functions.addMember(delegation_address, current_quorum + 1).transact({'from': consensus_admin})

    # Warp time past one frame + fast lane to guarantee a fresh frame outside the fast-lane window
    frame_config = hash_consensus.functions.getFrameConfig().call()
    epochs_per_frame = frame_config[1]
    fast_lane_length_slots = frame_config[2]
    frame_duration = epochs_per_frame * 32 * 12
    fast_lane_duration = fast_lane_length_slots * 12
    current_timestamp = web3_with_delegation.eth.get_block('latest')['timestamp']
    web3_with_delegation.provider.make_request(
        'evm_setNextBlockTimestamp',
        [current_timestamp + frame_duration + fast_lane_duration],
    )
    web3_with_delegation.provider.make_request('evm_mine', [])

    return hash_consensus


@pytest.mark.testnet
@pytest.mark.fork
@pytest.mark.integration
@pytest.mark.parametrize('running_finalized_slots', [finalized_slots], indirect=True)
class TestDelegationFork:
    def test_check_and_send_transaction__submit_report_via_delegation__transaction_succeeds(
        self,
        delegatee_account,
        web3_with_delegation,
        hash_consensus_with_delegation_member,
        delegation_address,
    ):
        # Arrange
        _, delegatee_pk = delegatee_account
        hash_consensus = hash_consensus_with_delegation_member

        frame = hash_consensus.functions.getCurrentFrame().call()
        ref_slot = frame[0]
        report_hash = Web3.keccak(text="TestDelegationReport")
        consensus_version = web3_with_delegation.lido_contracts.accounting_oracle.functions.getConsensusVersion().call()

        target_call = hash_consensus.functions.submitReport(ref_slot, report_hash, consensus_version)
        account = Account.from_key(delegatee_pk)

        # Act
        receipt = web3_with_delegation.transaction.check_and_send_transaction(target_call, account)

        # Assert
        assert receipt is not None
        assert receipt['status'] == 1
        assert receipt['to'].lower() == delegation_address.lower()

        report_received_logs = hash_consensus.events.ReportReceived().process_receipt(receipt)
        assert len(report_received_logs) == 1
        assert report_received_logs[0]['args']['member'] == delegation_address
        assert report_received_logs[0]['args']['report'] == report_hash
        assert report_received_logs[0]['args']['refSlot'] == ref_slot

        trace = web3_with_delegation.provider.make_request(
            'debug_traceTransaction',
            [receipt['transactionHash'].hex(), {'tracer': 'callTracer'}],
        )
        inner_call = trace['result']['calls'][0]
        assert inner_call['from'].lower() == delegation_address.lower()
        assert inner_call['to'].lower() == hash_consensus.address.lower()

        member_state = hash_consensus.functions.getConsensusStateForMember(delegation_address).call()
        assert member_state.isMember is True
        assert member_state.lastMemberReportRefSlot == ref_slot
        assert member_state.currentFrameMemberReport == report_hash
