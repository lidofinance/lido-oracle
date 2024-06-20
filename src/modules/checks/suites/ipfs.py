"""IPFS provider"""


import pytest
from faker import Faker

from src.main import ipfs_providers
from src.providers.ipfs.public import PublicIPFS
from src.providers.ipfs.types import IPFSError, IPFSProvider


@pytest.fixture()
def content():
    return Faker().text()


@pytest.mark.parametrize("provider", ipfs_providers(), ids=lambda p: p.__class__.__name__)
def check_ipfs_provider(provider: IPFSProvider, content: str):
    """Checks that configured IPFS providers can be used by CSM"""

    if isinstance(provider, PublicIPFS):
        pytest.skip("PublicIPFS doesn't support pinning")

    try:
        cid = provider.publish(content.encode())
        ret = provider.fetch(cid).decode()
        if ret != content:
            raise IPFSError(f"Content mismatch, got={ret}, expected={content}")
    except IPFSError as e:
        raise AssertionError(f"Provider {provider.__class__.__name__} is not working") from e
