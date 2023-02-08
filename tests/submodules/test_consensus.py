import pytest

from src.modules.submodules.consensus import ConsensusModule

pytestmark = pytest.mark.skip(reason="Need to set-up report_contract address")


@pytest.fixture
def consensus(web3, consensus_client):
    return ConsensusModule(web3, consensus_client)


def test_init_submodule(consensus):
    pass
