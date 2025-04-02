"""IPFS provider"""

import random
import string

import pytest

from src import variables
from src.main import ipfs_providers
from src.providers.ipfs import GW3, IPFSError, IPFSProvider, Pinata, PublicIPFS


@pytest.fixture()
def content():
    letters = string.ascii_letters
    return "".join(random.choice(letters) for _ in range(255))


def providers():
    configured_providers = tuple(ipfs_providers())

    for typ in (GW3, Pinata):
        try:
            provider = [p for p in configured_providers if isinstance(p, typ)].pop()
        except IndexError:
            yield pytest.param(
                None,
                marks=pytest.mark.skip(f"{typ.__name__} provider is not configured"),
                id=typ.__name__,
            )
        else:
            yield pytest.param(provider, id=typ.__name__)


@pytest.mark.parametrize("provider", providers())
def check_ipfs_provider(provider: IPFSProvider, content: str):
    """Checks that configured IPFS provider can be used by CSM"""

    try:
        cid = provider.publish(content.encode())
        ret = provider.fetch(cid).decode()
        if ret != content:
            raise IPFSError(f"Content mismatch, got={ret}, expected={content}")
    except IPFSError as e:
        raise AssertionError(f"Provider {provider.__class__.__name__} is not working") from e


def check_csm_requires_ipfs_provider():
    if not variables.CSM_MODULE_ADDRESS:
        pytest.skip("IPFS provider is not requirement for non-CSM oracle")

    providers = [p for p in ipfs_providers() if not isinstance(p, PublicIPFS)]
    if not providers:
        pytest.fail("CSM oracle requires IPFS provider with pinnig support")
