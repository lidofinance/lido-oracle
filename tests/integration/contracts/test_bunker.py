import pytest

from src.modules.accounting.types import SharesRequestedToBurn
from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.integration
def test_burner(burner_contract, caplog):
    check_contract(
        burner_contract,
        [
            ('get_shares_requested_to_burn', None, lambda response: check_value_type(response, SharesRequestedToBurn)),
        ],
        caplog,
    )
