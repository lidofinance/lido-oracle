import pytest
from web3 import Web3, HTTPProvider

from src import variables
from src.modules.accounting.accounting import Accounting
from src.modules.ejector.ejector import Ejector
from tests.e2e import do_deposits, NO_ADDRESS
from tests.e2e.conftest import wait_for_message_appeared


@pytest.mark.e2e
def test_app(start_accounting, caplog):
    wait_for_message_appeared(caplog, "{'msg': 'Run module as daemon.'}", timeout=10)
    wait_for_message_appeared(caplog, "{'msg': 'Check if main data was submitted.', 'value': False}")
    wait_for_message_appeared(caplog, "{'msg': 'Check if contract could accept report.', 'value': True}")
    wait_for_message_appeared(caplog, "{'msg': 'Execute module.'}")
    wait_for_message_appeared(caplog, "{'msg': 'Checking bunker mode'}", timeout=1800)
    wait_for_message_appeared(caplog, "{'msg': 'Send report hash. Consensus version: [1]'}")


@pytest.mark.e2e
def test_accounting_with_two_modules(accounting_web3, setup_accounting_account, remove_sleep, caplog):
    do_deposits(accounting_web3, 4, 2)
    a = Accounting(accounting_web3)

    assert accounting_web3.lido_contracts.lido.functions.balanceOf(NO_ADDRESS).call() == 0
    assert a.is_contract_reportable(a._get_latest_blockstamp())
    a.cycle_handler()

    w3 = Web3(HTTPProvider(variables.EXECUTION_CLIENT_URI[0]))

    sent_tx = list(filter(lambda msg: msg.msg['msg'] == 'Transaction is in blockchain.', caplog.records))

    sent_accounting_tx = accounting_web3.eth.get_transaction(sent_tx[1].msg['transactionHash'])
    sent_accounting_report = accounting_web3.lido_contracts.accounting_oracle.decode_function_input(sent_accounting_tx['input'])[1]

    accounting_tx = w3.eth.get_transaction('0xd418066cc84af20e9b4ca215ba855e6d00d0a7b7107a5d1a96442aef8e5d280f')
    accounting_report = accounting_web3.lido_contracts.accounting_oracle.decode_function_input(accounting_tx['input'])[1]

    assert sent_accounting_report['data']['refSlot'] == accounting_report['data']['refSlot']
    assert sent_accounting_report['data']['numValidators'] == accounting_report['data']['numValidators'] + 3
    # Two validators has balances and one is withdrawn
    assert accounting_report['data']['clBalanceGwei'] + 2 * 32 * 10**9 - 10**9 <= sent_accounting_report['data']['clBalanceGwei'] <= accounting_report['data']['clBalanceGwei'] + 2 * 32 * 10**9 + 10**9
    # Module #2 has 1 exited validator
    assert sent_accounting_report['data']['stakingModuleIdsWithNewlyExitedValidators'] == [2]
    assert sent_accounting_report['data']['numExitedValidatorsByStakingModule'] == [1]

    # Check rewards are there
    assert accounting_web3.lido_contracts.lido.functions.balanceOf(NO_ADDRESS).call() != 0

    extra_data_tx = w3.eth.get_transaction('0xad1c66f659572395cbe5afe111514f86192fdecb4be4e166f48ad7ce886a7876')
    extra_data_report = accounting_web3.lido_contracts.accounting_oracle.decode_function_input(extra_data_tx['input'])[1]

    assert not extra_data_report

    sent_extra_data_tx = accounting_web3.eth.get_transaction(sent_tx[2].msg['transactionHash'])
    sent_extra_data_report = accounting_web3.lido_contracts.accounting_oracle.decode_function_input(sent_extra_data_tx['input'])[1]

    assert sent_extra_data_report['items']

    # Item index
    assert sent_extra_data_report['items'][2] == 0
    # Item type
    assert sent_extra_data_report['items'][4] == 1
    # moduleId
    assert sent_extra_data_report['items'][7] == 2
    # NO count
    assert sent_extra_data_report['items'][15] == 1
    # NO ids
    assert sent_extra_data_report['items'][23] == 0
    # NO stuck vals count
    assert sent_extra_data_report['items'][39] == 1

    # Item index
    assert sent_extra_data_report['items'][42] == 1
    # Item type
    assert sent_extra_data_report['items'][44] == 2
    # moduleId
    assert sent_extra_data_report['items'][47] == 2
    # NO count
    assert sent_extra_data_report['items'][55] == 1
    # NO ids
    assert sent_extra_data_report['items'][63] == 0
    # NO active vals count
    assert sent_extra_data_report['items'][79] == 1

    assert not a.is_contract_reportable(a._get_latest_blockstamp())


def test_ejector_two_modules(ejector_web3, setup_ejector_account, remove_sleep, caplog):
    e = Ejector(ejector_web3)

    assert e.is_contract_reportable(e._get_latest_blockstamp())
    e.cycle_handler()

    latest = e._get_latest_blockstamp()
    events = ejector_web3.lido_contracts.validators_exit_bus_oracle.events.ValidatorExitRequest.get_logs(fromBlock=latest.block_number - 5)

    assert events[0]['args']['stakingModuleId'] == 2
    assert events[0]['args']['nodeOperatorId'] == 0
