from unittest.mock import MagicMock, patch

import pytest

from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import IPFSError, IPFSProvider
from src.types import FrameNumber
from src.web3py.extensions.ipfs import IPFS, MaxRetryError, NoMoreProvidersError


HARDCODED_CID = CID("QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn")
HARDCODED_FETCH_CONTENT = b"hardcoded_fetched_content"


class MockIPFSProvider(IPFSProvider):

    def __init__(self, name):
        self.name = name

    def fetch(self, cid: CID) -> bytes:
        return HARDCODED_FETCH_CONTENT

    def _upload(self, content: bytes, name: str | None = None) -> str:
        return str(HARDCODED_CID)

    def pin(self, cid: CID) -> None:
        pass


@pytest.mark.unit
class TestIPFS:

    @pytest.fixture
    def mock_w3(self):
        return MagicMock()

    @pytest.fixture
    def mock_provider1(self):
        return MockIPFSProvider("provider1")

    @pytest.fixture
    def mock_provider2(self):
        return MockIPFSProvider("provider2")

    def test_init__valid_parameters__creates_ipfs_instance(self, mock_w3, mock_provider1):
        ipfs = IPFS(mock_w3, [mock_provider1])
        assert ipfs.w3 == mock_w3
        assert ipfs.providers == [mock_provider1]
        assert ipfs.retries == 3

    def test_init__empty_providers_list__raises_assertion_error(self, mock_w3):
        with pytest.raises(AssertionError):
            IPFS(mock_w3, [])

    def test_init__invalid_provider_type__raises_assertion_error(self, mock_w3):
        with pytest.raises(AssertionError):
            IPFS(mock_w3, ["not a provider"])

    def test_provider_selection__different_frames__rotates_providers(self, mock_w3, mock_provider1, mock_provider2):
        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2])
        cid = CID("any_cid")

        ipfs.fetch(cid, FrameNumber(0))
        assert ipfs.provider == mock_provider1

        ipfs.publish(b"", FrameNumber(1), "")
        assert ipfs.provider == mock_provider2

        ipfs.fetch(cid, FrameNumber(2))
        assert ipfs.provider == mock_provider1

        ipfs.fetch(cid, FrameNumber(3))
        assert ipfs.provider == mock_provider2

    def test_provider_selection__same_frame__keeps_same_provider(self, mock_w3, mock_provider1, mock_provider2):
        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2])
        cid = CID("any_cid")

        ipfs.fetch(cid, FrameNumber(1))
        assert ipfs.provider == mock_provider2

        ipfs.fetch(cid, FrameNumber(1))
        assert ipfs.provider == mock_provider2

        ipfs.publish(b"", FrameNumber(1), "")
        assert ipfs.provider == mock_provider2

    def test_fetch__valid_cid__returns_content(self, mock_w3, mock_provider1):
        ipfs = IPFS(mock_w3, [mock_provider1])
        cid = CID("any_cid")
        result = ipfs.fetch(cid, FrameNumber(0))
        assert result == HARDCODED_FETCH_CONTENT

    def test_publish__valid_content__returns_cid(self, mock_w3, mock_provider1):
        ipfs = IPFS(mock_w3, [mock_provider1])
        content = b"any_content"
        name = "any_name"
        cid = ipfs.publish(content, FrameNumber(0), name)
        assert cid == HARDCODED_CID

    def test_fetch__first_attempt_fails__retries_and_succeeds(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.fetch = MagicMock(side_effect=[IPFSError("fail"), HARDCODED_FETCH_CONTENT])
        ipfs = IPFS(mock_w3, [provider], retries=2)
        result = ipfs.fetch(HARDCODED_CID, FrameNumber(0))
        assert result == HARDCODED_FETCH_CONTENT
        assert provider.fetch.call_count == 2

    def test_fetch__all_retries_fail__raises_no_more_providers_error(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.fetch = MagicMock(side_effect=IPFSError("fail"))
        ipfs = IPFS(mock_w3, [provider], retries=3)
        with pytest.raises(NoMoreProvidersError) as excinfo:
            ipfs.fetch(HARDCODED_CID, FrameNumber(0))
        assert isinstance(excinfo.value.__cause__, MaxRetryError)
        assert provider.fetch.call_count == 3

    def test_fetch__first_provider_fails__falls_back_to_second_provider(self, mock_w3, mock_provider1, mock_provider2):
        provider1 = mock_provider1
        provider1.fetch = MagicMock(side_effect=Exception("fail"))
        provider2 = mock_provider2
        provider2.fetch = MagicMock(return_value=HARDCODED_FETCH_CONTENT)

        ipfs = IPFS(mock_w3, [provider1, provider2])
        result = ipfs.fetch(HARDCODED_CID, FrameNumber(0))

        assert result == HARDCODED_FETCH_CONTENT
        assert provider1.fetch.call_count == 1
        assert provider2.fetch.call_count == 1

    def test_fetch__all_providers_fail__raises_no_more_providers_error(self, mock_w3, mock_provider1, mock_provider2):
        provider1 = mock_provider1
        provider1.fetch = MagicMock(side_effect=Exception("fail1"))
        provider2 = mock_provider2
        provider2.fetch = MagicMock(side_effect=Exception("fail2"))

        ipfs = IPFS(mock_w3, [provider1, provider2])

        with pytest.raises(NoMoreProvidersError) as excinfo:
            ipfs.fetch(HARDCODED_CID, FrameNumber(0))
        assert "fail2" in str(excinfo.value.__cause__)

        assert provider1.fetch.call_count == 1
        assert provider2.fetch.call_count == 1

    def test_publish__first_attempt_fails__retries_and_succeeds(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.publish = MagicMock(side_effect=[IPFSError("fail"), HARDCODED_CID])
        ipfs = IPFS(mock_w3, [provider], retries=2)
        result = ipfs.publish(b"test", FrameNumber(0), "test")
        assert result == HARDCODED_CID
        assert provider.publish.call_count == 2

    def test_publish__all_retries_fail__raises_no_more_providers_error(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.publish = MagicMock(side_effect=IPFSError("fail"))
        ipfs = IPFS(mock_w3, [provider], retries=3)
        with pytest.raises(NoMoreProvidersError) as excinfo:
            ipfs.publish(b"test", FrameNumber(0), "test")
        assert isinstance(excinfo.value.__cause__, MaxRetryError)
        assert provider.publish.call_count == 3

    def test_publish__first_provider_fails__falls_back_to_second_provider(
        self, mock_w3, mock_provider1, mock_provider2
    ):
        provider1 = mock_provider1
        provider1.publish = MagicMock(side_effect=Exception("fail"))
        provider2 = mock_provider2
        provider2.publish = MagicMock(return_value=HARDCODED_CID)

        ipfs = IPFS(mock_w3, [provider1, provider2])
        result = ipfs.publish(b"test", FrameNumber(0), "test")

        assert result == HARDCODED_CID
        assert provider1.publish.call_count == 1
        assert provider2.publish.call_count == 1

    def test_publish__all_providers_fail__raises_no_more_providers_error(self, mock_w3, mock_provider1, mock_provider2):
        provider1 = mock_provider1
        provider1.publish = MagicMock(side_effect=Exception("fail1"))
        provider2 = mock_provider2
        provider2.publish = MagicMock(side_effect=Exception("fail2"))

        ipfs = IPFS(mock_w3, [provider1, provider2])

        with pytest.raises(NoMoreProvidersError) as excinfo:
            ipfs.publish(b"test", FrameNumber(0), "test")
        assert "fail2" in str(excinfo.value.__cause__)

        assert provider1.publish.call_count == 1
        assert provider2.publish.call_count == 1
