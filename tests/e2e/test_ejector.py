import pytest
from web3 import Web3, HTTPProvider

from src import variables
from src.modules.ejector.ejector import Ejector
from tests.e2e.conftest import set_only_guardian, ADMIN, increase_balance


REF_SLOT = 8788799
REF_BLOCK = 19587022


@pytest.mark.e2e
@pytest.mark.parametrize("web3_anvil", [(REF_SLOT, REF_BLOCK)], indirect=["web3_anvil"])
def test_ejector_report(web3_anvil, remove_sleep, caplog):
    web3 = Web3(HTTPProvider(variables.EXECUTION_CLIENT_URI[0]))

    e = Ejector(web3_anvil)

    latest = e._get_latest_blockstamp()

    consensus = e._get_consensus_contract(latest)

    increase_balance(web3_anvil, ADMIN, 10**18)
    increase_balance(web3_anvil, variables.ACCOUNT.address, 10**18)

    set_only_guardian(consensus, variables.ACCOUNT.address, ADMIN)

    assert e.is_contract_reportable(e._get_latest_blockstamp())

    e.cycle_handler()

    sent_tx = list(filter(lambda msg: msg.msg['msg'] == 'Transaction is in blockchain.', caplog.records))

    assert len(sent_tx) == 2
    tx_2 = web3_anvil.eth.get_transaction(sent_tx[1].msg['transactionHash'])
    report_2 = web3_anvil.lido_contracts.validators_exit_bus_oracle.decode_function_input(tx_2['input'])[1]

    actual_tx_2 = web3.eth.get_transaction('0xdcc846c3e433ee538ca5a75471ac75aca29059e46a872d0e11c662de4db52148')
    actual_report_2 = web3_anvil.lido_contracts.validators_exit_bus_oracle.decode_function_input(actual_tx_2['input'])[1]

    assert actual_report_2 == report_2
