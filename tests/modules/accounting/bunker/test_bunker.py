import pytest

from src.modules.accounting.typings import LidoReportRebase
from tests.modules.accounting.bunker.conftest import simple_ref_blockstamp


@pytest.mark.unit
@pytest.mark.parametrize(
    ("simulated_post_total_pooled_ether", "expected_rebase"),
    [
        (15 * 10 ** 18, 0),
        (12 * 10 ** 18, -3 * 10 ** 9),
        (18 * 10 ** 18, 3 * 10 ** 9),
    ]
)
def test_get_cl_rebase_for_frame(
    bunker,
    mock_get_total_supply,
    simulated_post_total_pooled_ether,
    expected_rebase,
):
    blockstamp = simple_ref_blockstamp(0)
    simulated_cl_rebase = LidoReportRebase(
        post_total_pooled_ether=simulated_post_total_pooled_ether,
        post_total_shares=0,
        withdrawals=0,
        el_reward=0,
    )

    result = bunker.get_cl_rebase_for_current_report(blockstamp, simulated_cl_rebase)

    assert result == expected_rebase
