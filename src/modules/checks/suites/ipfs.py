"""IPFS provider"""

import random
import string

from src.main import ipfs_providers
from src.providers.ipfs import Pinata, Storacha

REQUIRED_PROVIDERS = (Pinata, Storacha)


def check_ipfs_providers():
    """Checks:
    1. Required providers (Pinata, Storacha) are configured
    2. Cross-compatibility - CIDs and content between different IPFS providers must be the same
    3. Provider stability - Non-working providers will return HTTP errors
    4. Authentication - If credentials are incorrect, upload/fetch will fail

    Warning! Parametrize decorator is not used here to avoid parallel run via pytest-xdist
    """
    configured_providers = list(ipfs_providers())

    missing_providers = []
    for required_provider in REQUIRED_PROVIDERS:
        provider_configured = any(isinstance(p, required_provider) for p in configured_providers)
        if not provider_configured:
            missing_providers.append(required_provider.__name__)

    assert not missing_providers, f"Required providers not configured: {', '.join(missing_providers)}"

    errors = []

    for upload_provider in configured_providers:
        test_content = "".join(random.choice(string.printable) for _ in range(128))

        try:
            uploaded_cid = upload_provider.publish(test_content.encode())
        except Exception as e:  # pylint: disable=broad-exception-caught
            errors.append(
                f"Upload failed on provider {upload_provider.__class__.__name__} during publish stage: "
                f"{type(e).__name__}: {e}"
            )
            continue

        downloaded_contents = {}

        # Check content between different IPFS providers
        for download_provider in configured_providers:
            try:
                downloaded_content = download_provider.fetch(uploaded_cid).decode()
                downloaded_contents[download_provider.__class__.__name__] = downloaded_content
            except Exception as e:  # pylint: disable=broad-exception-caught
                errors.append(
                    f"Download failed on provider {download_provider.__class__.__name__} during fetch stage "
                    f"for CID {uploaded_cid} (uploaded via {upload_provider.__class__.__name__}): "
                    f"{type(e).__name__}: {e}"
                )
                continue

            if downloaded_content != test_content:
                errors.append(
                    f"Content mismatch: uploaded via {upload_provider.__class__.__name__}, "
                    f"downloaded via {download_provider.__class__.__name__} for CID {uploaded_cid}: "
                    f"expected {test_content}, got {downloaded_content}"
                )

        # Check CID's between different IPFS providers
        # Separate cycle to avoid corruption of fetched content checking
        for download_provider in configured_providers:
            if download_provider.__class__.__name__ not in downloaded_contents:
                continue

            downloaded_content = downloaded_contents[download_provider.__class__.__name__]

            try:
                download_cid = download_provider.publish(downloaded_content.encode())
            except Exception as e:  # pylint: disable=broad-exception-caught
                errors.append(
                    f"Re-upload failed on provider {download_provider.__class__.__name__} during publish stage "
                    f"for content from {upload_provider.__class__.__name__}: {type(e).__name__}: {e}"
                )
                continue

            if download_cid != uploaded_cid:
                errors.append(
                    f"CID mismatch: uploaded via {upload_provider.__class__.__name__}, "
                    f"re-uploaded via {download_provider.__class__.__name__}: "
                    f"expected {uploaded_cid}, got {download_cid}"
                )

    numbered_errors = [f"{i+1}. {error}" for i, error in enumerate(errors)]
    assert not errors, f"Provider issues found ({len(errors)} total):\n" + "\n".join(numbered_errors)
