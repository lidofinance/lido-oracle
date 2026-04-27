import json

import pytest
from eth_abi import decode
from web3 import Web3

from src import variables
from src.utils.version import get_oracle_version
from src.web3py.extensions.telemetry_data_bus import TelemetryDataBus, TelemetryEventId


@pytest.fixture()
def blockstamp_for_forking():
    # None gives fork from latest block
    return None


@pytest.mark.testnet
@pytest.mark.fork
@pytest.mark.integration
class TestTelemetryDataBusFork:
    def test_send_telemetry__on_testnet_fork__transaction_succeeds(
        self,
        forked_el_client,
        accounts_from_fork,
        account_from,
    ):
        # Arrange
        addresses, private_keys = accounts_from_fork
        sender_address = addresses[0]
        sender_pk = private_keys[0]

        forked_el_client.provider.make_request('anvil_setBalance', [sender_address, hex(10**18)])

        anvil_url = forked_el_client.provider.endpoint_uri
        data_bus_address = variables.DATA_BUS_ADDRESS

        telemetry = TelemetryDataBus(
            data_bus_rpc=anvil_url,
            data_bus_address=data_bus_address,
            module_name='accounting',
            w3=forked_el_client,
        )

        report_data = (1, 2, 3, 100, 200)
        report_hash = Web3.keccak(text="test_report_hash")

        # Act
        with account_from(sender_pk):
            data = {'report_hash': '0x' + report_hash.hex(), 'report': list(report_data)}
            telemetry.send_telemetry(TelemetryEventId.ORACLE_REPORT, data)

        # Assert
        latest_block = forked_el_client.eth.get_block('latest', full_transactions=True)
        tx_hash = latest_block['transactions'][-1]['hash']
        receipt = forked_el_client.eth.get_transaction_receipt(tx_hash)
        log = receipt['logs'][0]

        (payload_bytes,) = decode(['bytes'], bytes(log['data']))
        payload = json.loads(payload_bytes.decode('utf-8'))

        assert payload['chain_id'] == forked_el_client.eth.chain_id
        assert payload['module'] == 'accounting'
        assert payload['version'] == get_oracle_version()
        assert payload['data']['report_hash'] == '0x' + report_hash.hex()
        assert payload['data']['report'] == list(report_data)
