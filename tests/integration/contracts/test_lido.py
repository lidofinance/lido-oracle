import pytest

from src.modules.accounting.types import LidoReportRebase, BeaconStat
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
                    1744632011,  # timestamp
                    86400,
                    389746,
                    9303747261167584000000000,
                    1337759360109000000000,
                    119464421677104745350,
                    0,
                    accounting_oracle_contract.address,
                    20390705,
                    # Call depends on contract state
                    '0xfbd1037bb43913198d5c8415a1d059afde09bf0dc56e250f5ff2bd2410c16dd2',
                ),
                lambda response: check_value_type(response, LidoReportRebase),
            ),
        ],
        caplog,
    )
