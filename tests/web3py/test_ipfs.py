from unittest.mock import MagicMock, patch

import pytest

from src.providers.ipfs.cid import CID
from src.providers.ipfs.types import IPFSError, IPFSProvider
from src.types import FrameNumber
from src.web3py.extensions.ipfs import IPFS, MaxRetryError, NoMoreProvidersError, ProviderConsistencyError


HARDCODED_FETCH_CONTENT = b"hardcoded_fetched_content"
HARDCODED_FETCH_CID = CID("QmWWiPYSquMJAizMhWMimhmZiHdz8Q9owhv9NyzZm4RDX3")
HARDCODED_PUBLISH_CONTENT = b"any_content"
HARDCODED_PUBLISH_CID = CID("QmdAjYn2fs94anbsRsTxYkjpaRSaCv7uz9pMnSwiivW77J")


def create_mock_provider_class(name: str):
    def _fetch(self, cid: CID) -> bytes:
        return HARDCODED_FETCH_CONTENT

    def _upload(self, content: bytes, name: str | None = None) -> str:
        return str(HARDCODED_PUBLISH_CID)

    def pin(self, cid: CID) -> None:
        pass

    return type(name, (IPFSProvider,), {'_fetch': _fetch, '_upload': _upload, 'pin': pin})


MockProvider1 = create_mock_provider_class("MockProvider1")
MockProvider2 = create_mock_provider_class("MockProvider2")
MockProvider3 = create_mock_provider_class("MockProvider3")
MockProvider4 = create_mock_provider_class("MockProvider4")


@pytest.mark.unit
class TestIPFS:

    @pytest.fixture
    def mock_w3(self):
        return MagicMock()

    @pytest.fixture
    def mock_provider1(self):
        return MockProvider1()

    @pytest.fixture
    def mock_provider2(self):
        return MockProvider2()

    @pytest.fixture
    def mock_provider3(self):
        return MockProvider3()

    @pytest.fixture
    def mock_provider4(self):
        return MockProvider4()

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

    def test_providers_order__shuffled_once_at_init__order_remain_the_same_during_operations(
        self, mock_w3, mock_provider1, mock_provider2
    ):
        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2])
        initial_providers_order = ipfs.providers[:]

        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))
        ipfs.publish(HARDCODED_PUBLISH_CONTENT, "test")
        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(2))

        assert ipfs.providers == initial_providers_order

    @patch('random.shuffle')
    def test_provider_selection__different_frames__rotates_providers_for_fetch_only(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2])

        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))
        assert ipfs.provider == mock_provider1

        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(1))
        assert ipfs.provider == mock_provider2

        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(2))
        assert ipfs.provider == mock_provider1

    @patch('random.shuffle')
    def test_provider_selection__same_frame__keeps_same_provider_for_fetch(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2])

        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(1))
        assert ipfs.provider == mock_provider2

        ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(1))
        assert ipfs.provider == mock_provider2

    def test_fetch__valid_cid__returns_content(self, mock_w3, mock_provider1):
        ipfs = IPFS(mock_w3, [mock_provider1])
        result = ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))
        assert result == HARDCODED_FETCH_CONTENT

    def test_publish__valid_content__returns_cid(self, mock_w3, mock_provider1):
        ipfs = IPFS(mock_w3, [mock_provider1])
        name = "any_name"
        cid = ipfs.publish(HARDCODED_PUBLISH_CONTENT, name)
        assert cid == HARDCODED_PUBLISH_CID

    def test_fetch__first_attempt_fails__retries_and_succeeds(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.fetch = MagicMock(side_effect=[IPFSError("fail"), HARDCODED_FETCH_CONTENT])
        ipfs = IPFS(mock_w3, [provider], retries=2)
        result = ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))
        assert result == HARDCODED_FETCH_CONTENT
        assert provider.fetch.call_count == 2

    def test_fetch__all_retries_fail__raises_no_more_providers_error(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.fetch = MagicMock(side_effect=IPFSError("fail"))
        ipfs = IPFS(mock_w3, [provider], retries=3)
        with pytest.raises(NoMoreProvidersError) as excinfo:
            ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))
        assert isinstance(excinfo.value.__cause__, MaxRetryError)
        assert provider.fetch.call_count == 3

    @patch('random.shuffle')
    def test_fetch__first_provider_fails__falls_back_to_second_provider(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        provider1 = mock_provider1
        provider1.fetch = MagicMock(side_effect=Exception("fail"))
        provider2 = mock_provider2
        provider2.fetch = MagicMock(return_value=HARDCODED_FETCH_CONTENT)

        ipfs = IPFS(mock_w3, [provider1, provider2])
        result = ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))

        assert result == HARDCODED_FETCH_CONTENT
        assert provider1.fetch.call_count == 1
        assert provider2.fetch.call_count == 1

    @patch('random.shuffle')
    def test_fetch__all_providers_fail__raises_no_more_providers_error(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        provider1 = mock_provider1
        provider1.fetch = MagicMock(side_effect=Exception("fail1"))
        provider2 = mock_provider2
        provider2.fetch = MagicMock(side_effect=Exception("fail2"))

        ipfs = IPFS(mock_w3, [provider1, provider2])

        with pytest.raises(NoMoreProvidersError) as excinfo:
            ipfs.fetch(HARDCODED_FETCH_CID, FrameNumber(0))
        assert "fail2" in str(excinfo.value.__cause__)

        assert provider1.fetch.call_count == 1
        assert provider2.fetch.call_count == 1

    def test_publish__first_attempt_fails__retries_and_succeeds(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.publish = MagicMock(side_effect=[IPFSError("fail"), HARDCODED_PUBLISH_CID])
        ipfs = IPFS(mock_w3, [provider], retries=2)
        result = ipfs.publish(b"test", "test")
        assert result == HARDCODED_PUBLISH_CID
        assert provider.publish.call_count == 2

    def test_publish__all_retries_fail__raises_no_more_providers_error(self, mock_w3, mock_provider1):
        provider = mock_provider1
        provider.publish = MagicMock(side_effect=IPFSError("fail"))
        ipfs = IPFS(mock_w3, [provider], retries=3)
        with pytest.raises(NoMoreProvidersError):
            ipfs.publish(b"test", "test")
        assert provider.publish.call_count == 3

    @patch('random.shuffle')
    def test_publish__all_providers_succeed__uploads_to_all_providers(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        provider1 = mock_provider1
        provider1.publish = MagicMock(return_value=HARDCODED_PUBLISH_CID)
        provider2 = mock_provider2
        provider2.publish = MagicMock(return_value=HARDCODED_PUBLISH_CID)

        ipfs = IPFS(mock_w3, [provider1, provider2])
        result = ipfs.publish(b"test", "test")

        assert result == HARDCODED_PUBLISH_CID
        assert provider1.publish.call_count == 1
        assert provider2.publish.call_count == 1

    @patch('random.shuffle')
    def test_publish__all_providers_fail__raises_no_more_providers_error(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        provider1 = mock_provider1
        provider1.publish = MagicMock(side_effect=Exception("fail1"))
        provider2 = mock_provider2
        provider2.publish = MagicMock(side_effect=Exception("fail2"))

        ipfs = IPFS(mock_w3, [provider1, provider2])

        with pytest.raises(NoMoreProvidersError):
            ipfs.publish(b"test", "test")

        assert provider1.publish.call_count == 1
        assert provider2.publish.call_count == 1

    @patch('random.shuffle')
    def test_publish__some_providers_fail_some_succeed__returns_successful_cid(
        self, mock_shuffle, mock_w3, mock_provider1, mock_provider2
    ):
        mock_shuffle.return_value = None
        provider1 = mock_provider1
        provider1.publish = MagicMock(side_effect=Exception("fail"))
        provider2 = mock_provider2
        provider2.publish = MagicMock(return_value=HARDCODED_PUBLISH_CID)

        ipfs = IPFS(mock_w3, [provider1, provider2])
        result = ipfs.publish(b"test", "test")

        assert result == HARDCODED_PUBLISH_CID
        assert provider1.publish.call_count == 1
        assert provider2.publish.call_count == 1

    def test_publish_quorum__consensus_reached__returns_consensus_cid(
        self, mock_w3, mock_provider1, mock_provider2, mock_provider3
    ):
        consensus_cid = CID("QmConsensus")
        minority_cid = CID("QmMinority")

        mock_provider1.publish = MagicMock(return_value=consensus_cid)
        mock_provider2.publish = MagicMock(return_value=consensus_cid)
        mock_provider3.publish = MagicMock(return_value=minority_cid)

        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2, mock_provider3])
        result = ipfs.publish(b"test", "test")

        assert result == consensus_cid
        assert mock_provider1.publish.call_count == 1
        assert mock_provider2.publish.call_count == 1
        assert mock_provider3.publish.call_count == 1

    def test_publish_quorum__no_consensus__falls_back_to_priority_provider(
        self, mock_w3, mock_provider1, mock_provider2, mock_provider3
    ):
        cid1 = CID("QmCID1")
        cid2 = CID("QmCID2")
        cid3 = CID("QmCID3")

        mock_provider1.publish = MagicMock(return_value=cid1)
        mock_provider2.publish = MagicMock(return_value=cid2)
        mock_provider3.publish = MagicMock(return_value=cid3)

        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2, mock_provider3])
        result = ipfs.publish(b"test", "test")

        assert result == cid1
        assert mock_provider1.publish.call_count == 1
        assert mock_provider2.publish.call_count == 1
        assert mock_provider3.publish.call_count == 1

    def test_publish_quorum__four_providers_no_consensus__falls_back_to_second_priority(
        self, mock_w3, mock_provider1, mock_provider2, mock_provider3, mock_provider4
    ):
        cid2 = CID("QmCID2")
        cid3 = CID("QmCID3")
        cid4 = CID("QmCID4")

        mock_provider1.publish = MagicMock(side_effect=Exception("fail"))
        mock_provider2.publish = MagicMock(return_value=cid2)
        mock_provider3.publish = MagicMock(return_value=cid3)
        mock_provider4.publish = MagicMock(return_value=cid4)

        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2, mock_provider3, mock_provider4])
        result = ipfs.publish(b"test", "test")

        assert result == cid2
        assert mock_provider1.publish.call_count == 1
        assert mock_provider2.publish.call_count == 1
        assert mock_provider3.publish.call_count == 1
        assert mock_provider4.publish.call_count == 1

    def test_publish_quorum__four_providers_tie__falls_back_to_priority(
        self, mock_w3, mock_provider1, mock_provider2, mock_provider3, mock_provider4
    ):
        cid_a = CID("QmCIDA")
        cid_b = CID("QmCIDB")

        # Required quorum = (4 // 2) + 1 = 3, but each CID appears only 2 times
        mock_provider1.publish = MagicMock(return_value=cid_a)
        mock_provider2.publish = MagicMock(return_value=cid_a)
        mock_provider3.publish = MagicMock(return_value=cid_b)
        mock_provider4.publish = MagicMock(return_value=cid_b)

        ipfs = IPFS(mock_w3, [mock_provider1, mock_provider2, mock_provider3, mock_provider4])
        result = ipfs.publish(b"test", "test")

        assert result == cid_a
        assert mock_provider1.publish.call_count == 1
        assert mock_provider2.publish.call_count == 1
        assert mock_provider3.publish.call_count == 1
        assert mock_provider4.publish.call_count == 1
