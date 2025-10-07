import pytest

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.mainnet
@pytest.mark.integration
def test_burner(burner_contract, caplog):
    check_contract(
        burner_contract,
        [
            (
                'get_shares_requested_to_burn',
                None,
                lambda r: check_is_instance_of(int)(r.cover_shares) and check_is_instance_of(int)(r.non_cover_shares),
            ),
        ],
        caplog,
    )
