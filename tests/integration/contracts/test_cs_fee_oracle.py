import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.integration
def test_cs_fee_oracle(cs_fee_oracle_contract, caplog):
    check_contract(
        cs_fee_oracle_contract,
        [
            ("is_paused", ('latest',), make_checker(bool)),
        ],
        caplog,
    )


@pytest.mark.integration
def test_cs_fee_oracle_v2(cs_fee_oracle_contract, caplog):
    check_contract(
        cs_fee_oracle_contract,
        [
            ("strikes", ('latest',), make_checker(ChecksumAddress)),
        ],
        caplog,
    )
