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
                    1746275159,  # timestamp
                    86400,
                    389746,
                    9190764598468942000000000,
                    13771995248000000000,
                    478072602914417566,
                    0,
                    accounting_oracle_contract.address,
                    11620928,
                    # Call depends on contract state
                    '0xffa34bcc5a08c92272a62e591f7afb9cb839134aa08c091ae0c95682fba35da9',
                ),
                check_is_instance_of(LidoReportRebase),
            ),
        ],
        caplog,
    )
