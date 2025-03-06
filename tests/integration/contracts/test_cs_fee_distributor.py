import pytest
from eth_typing import ChecksumAddress
from hexbytes import HexBytes

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_cs_fee_distributor(cs_fee_distributor_contract, caplog):
    check_contract(
        cs_fee_distributor_contract,
        [
            ("oracle", None, check_is_instance_of(ChecksumAddress)),
            ("shares_to_distribute", None, check_is_instance_of(int)),
            ("tree_root", None, check_is_instance_of(HexBytes)),
            ("tree_cid", None, check_is_instance_of(str)),
        ],
        caplog,
    )
