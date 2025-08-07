"""IPFS provider"""

import random
import string

from src.main import ipfs_providers
from src.providers.ipfs import Pinata, PublicIPFS, Storacha

REQUIRED_PROVIDERS = (Pinata, Storacha)


def check_ipfs_providers():
    """Checks:
    1. Required providers (Pinata, Storacha) are configured
    2. Cross-compatibility - CIDs and content between different IPFS providers must be the same
    3. Provider stability - Non-working providers will return HTTP errors
    4. Authentication - If credentials are incorrect, upload/fetch will fail

    Warning! Parametrize decorator is not used here to avoid parallel run via pytest-xdist
    """
    configured_providers = [p for p in ipfs_providers() if not isinstance(p, PublicIPFS)]

    missing_providers = []
    for required_provider in REQUIRED_PROVIDERS:
        provider_configured = any(isinstance(p, required_provider) for p in configured_providers)
        if not provider_configured:
            missing_providers.append(required_provider.__name__)

    assert not missing_providers, f"Required providers not configured: {', '.join(missing_providers)}"

    errors = []

    for upload_provider in configured_providers:
        test_content = "".join(random.choice(string.printable) for _ in range(128))

        uploaded_cid = upload_provider.publish(test_content.encode())

        downloaded_contents = {}

        # Check content between different IPFS providers
        for download_provider in configured_providers:
            downloaded_content = download_provider.fetch(uploaded_cid).decode()
            downloaded_contents[download_provider.__class__.__name__] = downloaded_content

            if downloaded_content != test_content:
                errors.append(
                    f"Content mismatch: uploaded via {upload_provider.__class__.__name__}, "
                    f"downloaded via {download_provider.__class__.__name__} for CID {uploaded_cid}: "
                    f"expected {test_content}, got {downloaded_content}"
                )

        # Check CID's between different IPFS providers
        # Separate cycle to avoid corruption of fetched content checking
        for download_provider in configured_providers:
            downloaded_content = downloaded_contents[download_provider.__class__.__name__]
            download_cid = download_provider.publish(downloaded_content.encode())
            if download_cid != uploaded_cid:
                errors.append(
                    f"CID mismatch: uploaded via {upload_provider.__class__.__name__}, "
                    f"re-uploaded via {download_provider.__class__.__name__}: "
                    f"expected {uploaded_cid}, got {download_cid}"
                )

    assert not errors, "Provider compatibility issues found:\n" + "\n".join(errors)
