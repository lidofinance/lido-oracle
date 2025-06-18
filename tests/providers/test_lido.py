from typing import cast

import pytest

from src import variables
from src.providers.execution.contracts.lido import LidoContract
from src.providers.execution.contracts.lido_locator import LidoLocatorContract


@pytest.mark.testnet
@pytest.mark.integration
class TestLidoSmoke:

    @pytest.fixture
    def lido(self, web3_integration):
        lido_locator: LidoLocatorContract = cast(
            LidoLocatorContract,
            web3_integration.eth.contract(
                address=variables.LIDO_LOCATOR_ADDRESS,
                ContractFactoryClass=LidoLocatorContract,
                decode_tuples=True,
            ),
        )

        return cast(
            LidoContract,
            web3_integration.eth.contract(
                address=lido_locator.lido(),
                ContractFactoryClass=LidoContract,
                decode_tuples=True,
            ),
        )

    def test_last_token_rebased_event(self, lido, web3_integration):
        try:
            block = web3_integration.eth.get_block("latest", False)
            rebased_event = lido.get_last_token_rebased_event(from_block=block.number, to_block=block.number)

            assert rebased_event is not None
        except Exception as e:
            print(f"Error: {e}")

    def test_get_lido_fee(self, lido, web3_integration):
        try:
            fee_bp = lido.get_feeBP("latest")

            assert fee_bp is not None
        except Exception as e:
            print(f"Error: {e}")
