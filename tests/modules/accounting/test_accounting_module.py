import pytest

from modules.accounting.accounting import Accounting


@pytest.fixture
def accounting_module(web3):
    yield Accounting(web3)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("blockstamp", "expected_rebase"),
    [
        (simple_blockstamp(40, '0x40'), 378585831),
        (simple_blockstamp(20, '0x20'), 126195277),
    ]
)
def test_get_updated_modules_stats(accounting_module):
    accounting_module.get_updated_modules_stats(

    )
