import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_cs_fee_oracle(cs_fee_oracle_contract, caplog):
    check_contract(
        cs_fee_oracle_contract,
        [
            ("is_paused", None, check_is_instance_of(bool)),
        ],
        caplog,
    )


@pytest.mark.integration
def test_cs_fee_oracle_v2(cs_fee_oracle_contract, caplog):
    check_contract(
        cs_fee_oracle_contract,
        [
            ("strikes", None, check_is_instance_of(ChecksumAddress)),
        ],
        caplog,
    )
