import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, check_value_type, check_value_re, ADDRESS_REGREX


@pytest.mark.integration
def test_lido_locator_contract(lido_locator_contract, caplog):
    check_contract(
        lido_locator_contract,
        [
            (
                'accounting',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'accounting_oracle',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'burner',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'el_rewards_vault',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'lido',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'oracle_daemon_config',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'oracle_report_sanity_checker',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'staking_router',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'validator_exit_bus_oracle',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'vault_hub',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'withdrawal_queue',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
            (
                'withdrawal_vault',
                None,
                lambda response: check_value_re(ADDRESS_REGREX, response)
                and check_value_type(response, ChecksumAddress),
            ),
        ],
        caplog,
    )
