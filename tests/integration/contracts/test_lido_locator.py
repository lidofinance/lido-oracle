import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, make_checker


@pytest.mark.mainnet
@pytest.mark.integration
def test_lido_locator_contract(lido_locator_contract, caplog):
    check_contract(
        lido_locator_contract,
        [
            ('lido', ('latest',), make_checker(ChecksumAddress)),
            ('accounting_oracle', ('latest',), make_checker(ChecksumAddress)),
            ('staking_router', ('latest',), make_checker(ChecksumAddress)),
            ('validator_exit_bus_oracle', ('latest',), make_checker(ChecksumAddress)),
            ('withdrawal_queue', ('latest',), make_checker(ChecksumAddress)),
            ('oracle_report_sanity_checker', ('latest',), make_checker(ChecksumAddress)),
            ('oracle_daemon_config', ('latest',), make_checker(ChecksumAddress)),
            ('burner', ('latest',), make_checker(ChecksumAddress)),
            ('withdrawal_vault', ('latest',), make_checker(ChecksumAddress)),
            ('el_rewards_vault', ('latest',), make_checker(ChecksumAddress)),
        ],
        caplog,
    )


@pytest.mark.testnet
@pytest.mark.integration
def test_lido_locator_contract_testnet(lido_locator_contract, caplog):
    check_contract(
        lido_locator_contract,
        [
            ('accounting', ('latest',), make_checker(ChecksumAddress)),
            ('vault_hub', ('latest',), make_checker(ChecksumAddress)),
            ('lazy_oracle', ('latest',), make_checker(ChecksumAddress)),
        ],
        caplog,
    )
