import pytest

from src.typings import ReferenceBlockStamp
from src.services.safe_border import SafeBorder

@pytest.fixture()
def past_blockstamp():
    yield ReferenceBlockStamp(
        ref_slot=4947936,
        ref_epoch=154623,
        block_root='0xfc3a63409fe5c53c3bb06a96fc4caa89011452835f767e64bf59f2b6864037cc',
        state_root='0x7fcd917cbe34f306989c40bd64b8e2057a39dfbfda82025549f3a44e6b2295fc',
        slot_number=4947936,
        block_number=8457825,
        block_hash='0x0d61eeb26e4cbb076e557ddb8de092a05e2cba7d251ad4a87b0826cf5926f87b',
        block_timestamp=0
    )

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
