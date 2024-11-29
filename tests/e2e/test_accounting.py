import pytest
from eth_account import Account

from src import variables
from src.modules.accounting.accounting import Accounting
from tests.e2e.conftest import set_only_guardian, ADMIN, increase_balance


REF_SLOT = 10080104
REF_BLOCK = 20870610


@pytest.mark.e2e
@pytest.mark.parametrize("web3_anvil", [(REF_SLOT, REF_BLOCK)], indirect=["web3_anvil"])
def test_accounting_report(web3_anvil, caplog):
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

    sent_tx = list(
        filter(lambda msg: 'msg' in msg.msg and 'Transaction is in blockchain.' in msg.msg['msg'], caplog.records)
    )

    assert len(sent_tx) == 3
    tx_2 = web3_anvil.eth.get_transaction(sent_tx[1].msg['transactionHash'])
    report_2 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(tx_2['input'])[1]

    actual_tx_2 = web3_anvil.eth.get_transaction('0xb304e1720f5a1f933f50951a9c1db730d38589ed5e1449f45246a15e678b00ae')
    actual_report_2 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(actual_tx_2['input'])[1]

    assert actual_report_2 == report_2

    tx_3 = web3_anvil.eth.get_transaction(sent_tx[2].msg['transactionHash'])
    report_3 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(tx_3['input'])[1]

    actual_tx_3 = web3_anvil.eth.get_transaction('0x17686c974fd6d605c5bfc0f60eaf470e1dbe4abc08d6d0cf2194c2c6cbc1990d')
    actual_report_3 = web3_anvil.lido_contracts.accounting_oracle.decode_function_input(actual_tx_3['input'])[1]

    assert actual_report_3 == report_3
