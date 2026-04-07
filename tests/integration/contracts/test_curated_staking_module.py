import pytest

from tests.integration.contracts.contract_utils import check_contract, check_value_type


@pytest.mark.mainnet
@pytest.mark.integration
def test_curated_staking_module_contract(curated_staking_module_contract, caplog):
    check_contract(
        curated_staking_module_contract,
        [
            ('get_node_operator_weight', ([0, 1, 2], 'latest'), lambda r: check_value_type(r, list)),
            ('get_type', ('latest',), lambda r: check_value_type(r, bytes)),
            ('get_metaregistry_address', ('latest',), lambda r: check_value_type(r, str)),
        ],
        caplog,
    )
