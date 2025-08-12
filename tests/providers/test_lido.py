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
