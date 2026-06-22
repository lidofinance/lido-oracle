import pytest
from eth_typing import ChecksumAddress
from hexbytes import HexBytes

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.integration
def test_cs_fee_distributor(cs_fee_distributor_contract, caplog):
    check_contract(
        cs_fee_distributor_contract,
        [
            ("oracle", ('latest',), make_checker(ChecksumAddress)),
            ("shares_to_distribute", ('latest',), make_checker(int)),
            ("tree_root", ('latest',), make_checker(HexBytes)),
            ("tree_cid", ('latest',), make_checker(str)),
        ],
        caplog,
    )
