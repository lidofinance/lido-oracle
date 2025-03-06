import pytest

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.integration
def test_cs_fee_oracle(cs_fee_oracle_contract, caplog):
    check_contract(
        cs_fee_oracle_contract,
        [
            # ("strikes", None, check_is_instance_of(Address)), FIXME: Uncomment with CSMv2 live on mainnet.
            ("is_paused", None, check_is_instance_of(bool)),
        ],
        caplog,
    )
