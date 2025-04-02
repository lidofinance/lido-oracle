import pytest

from src.modules.accounting.types import SharesRequestedToBurn
from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_burner(burner_contract, caplog):
    check_contract(
        burner_contract,
        [
            ('get_shares_requested_to_burn', None, check_is_instance_of(SharesRequestedToBurn)),
        ],
        caplog,
    )
