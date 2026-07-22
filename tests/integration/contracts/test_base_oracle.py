import pytest
from eth_typing import ChecksumAddress
from web3.contract.contract import ContractFunction

from src.types import SlotNumber
from tests.integration.contracts.contract_utils import check_contract, check_value_type, make_checker


@pytest.mark.mainnet
@pytest.mark.integration
def test_base_oracle_via_vebo(validators_exit_bus_oracle_contract, caplog):
    """Tests BaseOracleContract methods via ValidatorsExitBusOracle (mainnet)."""
    role = validators_exit_bus_oracle_contract.submit_data_role('latest')
    assert isinstance(role, bytes) and len(role) == 32
    caplog.clear()

    check_contract(
        validators_exit_bus_oracle_contract,
        [
            ('get_consensus_contract', ('latest',), make_checker(ChecksumAddress)),
            ('submit_data_role', ('latest',), lambda r: check_value_type(r, bytes)),
            (
                'has_role',
                (role, validators_exit_bus_oracle_contract.address, 'latest'),
                lambda r: check_value_type(r, bool),
            ),
            ('get_contract_version', ('latest',), lambda r: check_value_type(r, int)),
            ('get_consensus_version', ('latest',), lambda r: check_value_type(r, int)),
            ('submit_report_data', ((0, 0, 0, 0, b''), 1), make_checker(ContractFunction)),
            ('get_last_processing_ref_slot', ('latest',), make_checker(SlotNumber)),
        ],
        caplog,
    )
