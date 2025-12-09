import pytest
from eth_typing import ChecksumAddress

from tests.integration.contracts.contract_utils import check_contract, check_is_instance_of


@pytest.mark.mainnet
@pytest.mark.integration
def test_lido_locator_contract(lido_locator_contract, caplog):
    check_contract(
        lido_locator_contract,
        [
            ('lido', None, check_is_instance_of(ChecksumAddress)),
            ('accounting_oracle', None, check_is_instance_of(ChecksumAddress)),
            ('staking_router', None, check_is_instance_of(ChecksumAddress)),
            ('validator_exit_bus_oracle', None, check_is_instance_of(ChecksumAddress)),
            ('withdrawal_queue', None, check_is_instance_of(ChecksumAddress)),
            ('oracle_report_sanity_checker', None, check_is_instance_of(ChecksumAddress)),
            ('oracle_daemon_config', None, check_is_instance_of(ChecksumAddress)),
            ('burner', None, check_is_instance_of(ChecksumAddress)),
            ('withdrawal_vault', None, check_is_instance_of(ChecksumAddress)),
            ('el_rewards_vault', None, check_is_instance_of(ChecksumAddress)),
        ],
        caplog,
    )


@pytest.mark.testnet
@pytest.mark.integration
def test_lido_locator_contract_testnet(lido_locator_contract, caplog):
    check_contract(
        lido_locator_contract,
        [
            ('accounting', None, check_is_instance_of(ChecksumAddress)),
            ('vault_hub', None, check_is_instance_of(ChecksumAddress)),
        ],
        caplog,
    )
