import pytest

from src.modules.accounting.types import BeaconStat, LidoReportRebase
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_lido_contract_call(lido_contract, accounting_oracle_contract, burner_contract, caplog):
    check_contract(
        lido_contract,
        [
            ('get_buffered_ether', None, lambda response: check_value_type(response, int)),
            ('total_supply', None, lambda response: check_value_type(response, int)),
            ('get_beacon_stat', None, lambda response: check_value_type(response, BeaconStat)),
            (
                'handle_oracle_report',
                (
                    1746275159,  # timestamp
                    86400,
                    403105,  # Updated to match current beacon_validators count
                    8461615483077294000000000,  # Updated to match current beacon_balance
                    13771995248000000000,
                    478072602914417566,
                    0,
                    accounting_oracle_contract.address,
                    11620928,
                    # Call depends on contract state
                    '0x4b7cf7dbb70179f2e0b6891972fa55903577a11008f6c87a309183829c8aebf1',
                ),
                lambda response: check_value_type(response, LidoReportRebase),
            ),
        ],
        caplog,
    )
