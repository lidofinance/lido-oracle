import pytest

from src.providers.execution.contracts.meta_registry import OperatorGroup
from tests.integration.contracts.contract_utils import check_contract, check_value_type, make_checker


@pytest.mark.mainnet
@pytest.mark.integration
@pytest.mark.skip("Enable after srv3 upgrade")
def test_meta_registry_contract(meta_registry_contract, caplog):
    check_contract(
        meta_registry_contract,
        [
            ('get_operator_groups_count', ('latest',), lambda r: check_value_type(r, int)),
            ('get_all_groups', ('latest',), lambda r: check_value_type(r, list)),
        ],
        caplog,
    )


@pytest.mark.mainnet
@pytest.mark.integration
@pytest.mark.skip("Enable after srv3 upgrade")
def test_meta_registry_get_operator_group(meta_registry_contract, caplog):
    count = meta_registry_contract.get_operator_groups_count(block_identifier='latest')
    if count == 0:
        pytest.skip("No operator groups on this network")
    caplog.clear()

    check_contract(
        meta_registry_contract,
        [
            ('get_operator_group', (1, 'latest'), make_checker(OperatorGroup)),
        ],
        caplog,
    )
