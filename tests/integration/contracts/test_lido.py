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
                    8462132592019028000000000,  # Updated to match current beacon_balance
                    13771995248000000000,
                    478072602914417566,
                    0,
                    accounting_oracle_contract.address,
                    11620928,  # ref_slot
                    '0x9bad2cb4e0ef017912b8c77e9ce1c6ec52a6b79013fe8d0d099a65a51ee4a66e',  # block_identifier
                ),
                lambda response: check_value_type(response, LidoReportRebase),
            ),
        ],
        caplog,
    )
