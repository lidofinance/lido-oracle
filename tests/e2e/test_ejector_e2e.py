import pytest
from eth_account import Account

from src import variables
from src.modules.ejector.ejector import Ejector
from tests.e2e.conftest import set_only_guardian, ADMIN, increase_balance


REF_SLOT = 10092111
REF_BLOCK = 20882570


@pytest.mark.e2e
@pytest.mark.parametrize("web3_anvil", [(REF_SLOT, REF_BLOCK)], indirect=["web3_anvil"])
def test_ejector_report(web3_anvil, caplog):
    e = Ejector(web3_anvil)

    latest = e._get_latest_blockstamp()

    consensus = e._get_consensus_contract(latest)

    increase_balance(web3_anvil, ADMIN, 10**18)
    variables.ACCOUNT = Account.from_key('0x66a484cf1a3c6ef8dfd59d24824943d2853a29d96f34a01271efc55774452a51')
    increase_balance(web3_anvil, variables.ACCOUNT.address, 10**18)

    set_only_guardian(consensus, variables.ACCOUNT.address, ADMIN)

    assert e.is_contract_reportable(e._get_latest_blockstamp())

    e.cycle_handler()

    sent_tx = list(
        filter(lambda msg: 'msg' in msg.msg and 'Transaction is in blockchain.' in msg.msg['msg'], caplog.records)
    )

    assert len(sent_tx) == 2
    tx_2 = web3_anvil.eth.get_transaction(sent_tx[1].msg['transactionHash'])
    report_2 = web3_anvil.lido_contracts.validators_exit_bus_oracle.decode_function_input(tx_2['input'])[1]

    actual_tx_2 = web3_anvil.eth.get_transaction('0x8cc36cd588c341fb91db82fab0de5d65a0d45cdbec07c76416da71df0ac7e98c')
    actual_report_2 = web3_anvil.lido_contracts.validators_exit_bus_oracle.decode_function_input(actual_tx_2['input'])[
        1
    ]

    assert actual_report_2 == report_2
