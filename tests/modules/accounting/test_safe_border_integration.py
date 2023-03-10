import pytest

from tests.factory.base import ReferenceBlockStampFactory


@pytest.fixture()
def past_blockstamp():
    yield ReferenceBlockStampFactory.build()


@pytest.fixture()
def subject(web3, contracts, keys_api_client, consensus_client):
    # return SafeBorder(web3)
    pass


@pytest.mark.skip(reason="waiting for testnet deployment")
def test_no_bunker_mode(subject, past_blockstamp):
    pass


@pytest.mark.skip(reason="waiting for testnet deployment")
def test_bunker_mode_associated_slashing(subject, past_blockstamp):
    pass


@pytest.mark.skip(reason="waiting for testnet deployment")
def test_bunker_mode_associated_slashing(subject, past_blockstamp):
    pass


@pytest.mark.skip(reason="waiting for testnet deployment")
def test_bunker_mode_negative_rebase(subject, past_blockstamp):
    pass
