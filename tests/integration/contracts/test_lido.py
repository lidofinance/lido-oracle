import pytest

from src.modules.accounting.types import LidoReportRebase, BeaconStat
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_lido_contract_call(lido_contract, accounting_oracle_contract, burner_contract, caplog):
    check_contract(
        lido_contract,
        [
            (
                'handle_oracle_report',
                (
                    1721995211,  # timestamp
                    86400,
                    368840,
                    9820580681659522000000000,
                    1397139100547000000000,
                    119464421677104745350,
                    0,
                    accounting_oracle_contract.address,
                    # Call depends on contract state
                    '0xfdc77ad0ea1ed99b1358beaca0d9c6fa831443f7f4c183302d9e2f76e4c9d0cb',
                ),
                lambda response: check_value_type(response, LidoReportRebase),
            ),
            ('get_buffered_ether', None, lambda response: check_value_type(response, int)),
            ('total_supply', None, lambda response: check_value_type(response, int)),
            ('get_beacon_stat', None, lambda response: check_value_type(response, BeaconStat)),
        ],
        caplog,
    )
