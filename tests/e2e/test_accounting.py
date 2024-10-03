import pytest
from eth_account import Account
from web3 import Web3, HTTPProvider

from src import variables
from src.modules.accounting.accounting import Accounting
from tests.e2e.conftest import set_only_guardian, ADMIN, increase_balance


REF_SLOT = 8783999
REF_BLOCK = 20877818


@pytest.mark.parametrize("web3_anvil", [(REF_SLOT, REF_BLOCK)], indirect=["web3_anvil"])
def test_accounting_report(web3_anvil, caplog):
    web3 = Web3(HTTPProvider(variables.EXECUTION_CLIENT_URI[0]))

    a = Accounting(web3_anvil)

    latest = a._get_latest_blockstamp()

    consensus = a._get_consensus_contract(latest)

    increase_balance(web3_anvil, ADMIN, 10**18)
    variables.ACCOUNT = Account.from_key('0x66a484cf1a3c6ef8dfd59d24824943d2853a29d96f34a01271efc55774452a51')
    increase_balance(web3_anvil, variables.ACCOUNT.address, 10**18)

    set_only_guardian(consensus, variables.ACCOUNT.address, ADMIN)
    reportable = a.is_contract_reportable(a._get_latest_blockstamp())

    assert reportable

    a.cycle_handler()

    sent_tx = list(filter(lambda msg: msg.msg == 'Transaction is in blockchain.', list(caplog.records)))

    assert len(sent_tx) == 3
    tx_2 = web3_anvil.eth.get_transaction(sent_tx[1].msg['transactionHash'])
    report_2 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(tx_2['input'])[1]

    actual_tx_2 = web3.eth.get_transaction('0xa471e41ffb29f7fd7f98ebf0036c356afbfd05630f3aecfe101bfd92a535aa1d')
    actual_report_2 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(actual_tx_2['input'])[1]

    assert actual_report_2 == report_2

    tx_3 = web3_anvil.eth.get_transaction(sent_tx[2].msg['transactionHash'])
    report_3 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(tx_3['input'])[1]

    actual_tx_3 = web3.eth.get_transaction('0x978f9e6c4f738c60f9f906a4fb6a9334e2b57b4f92b49bf5d4700f1b798c77ec')
    actual_report_3 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(actual_tx_3['input'])[1]

    assert actual_report_3 == report_3
