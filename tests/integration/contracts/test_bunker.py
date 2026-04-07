import pytest

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.mainnet
@pytest.mark.integration
def test_burner(burner_contract, caplog):
    check_contract(
        burner_contract,
        [
            (
                'get_shares_requested_to_burn',
                None,
                lambda r: make_checker(int)(r.cover_shares) and make_checker(int)(r.non_cover_shares),
            ),
        ],
        caplog,
    )
