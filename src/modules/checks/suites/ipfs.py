"""IPFS provider"""


import pytest


@pytest.fixture()
def content():
    return "ipfs.check"


def check_ipfs_provider(web3, content: str):
    """Checks that configured IPFS providers can be used by CSM"""
    cid = web3.ipfs.publish(content.encode())
    buf = web3.ipfs.fetch(cid)
    assert buf.decode() == content
