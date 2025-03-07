import pytest

from src.modules.accounting.types import LidoReportRebase, BeaconStat
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_lido_contract_call(lido_contract, accounting_oracle_contract, caplog):
    check_contract(
        lido_contract,
        [
            ('get_buffered_ether', None, check_is_instance_of(int)),
            ('total_supply', None, check_is_instance_of(int)),
            ('get_beacon_stat', None, check_is_instance_of(BeaconStat)),
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
                    20390705,
                    # Call depends on contract state
                    '0xfdc77ad0ea1ed99b1358beaca0d9c6fa831443f7f4c183302d9e2f76e4c9d0cb',
                ),
                check_is_instance_of(LidoReportRebase),
            ),
        ],
        caplog,
    )
