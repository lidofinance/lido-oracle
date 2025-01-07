import pytest

from src.modules.accounting.types import BeaconStat
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
@pytest.mark.parametrize('environment', ['holesky-vaults-devnet-2'], indirect=True)
def test_lido_contract_call(lido_contract, caplog):
    check_contract(
        lido_contract,
        [
            ('get_buffered_ether', None, lambda response: check_value_type(response, int)),
            ('total_supply', None, lambda response: check_value_type(response, int)),
            ('get_beacon_stat', None, lambda response: check_value_type(response, BeaconStat)),
        ],
        caplog,
    )
