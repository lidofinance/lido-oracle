import logging
from abc import ABC, abstractmethod
from http import HTTPStatus
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

from prometheus_client import Histogram
from requests import Session, JSONDecodeError
from requests.adapters import HTTPAdapter
from urllib3 import Retry

logger = logging.getLogger(__name__)


class NotOkResponse(Exception):
    status: int
    text: str

    def __init__(self, *args, status: int, text: str):
        self.status = status
        self.text = text
        super().__init__(*args)


class HTTPProvider(ABC):
    REQUEST_TIMEOUT = 300

    PROMETHEUS_HISTOGRAM: Histogram

    def __init__(self, host: str):
        self.host = host

        retry_strategy = Retry(
            total=5,
            status_forcelist=[418, 429, 500, 502, 503, 504],
            backoff_factor=5,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get(self, url: str, params: Optional[dict] = None) -> Tuple[dict | list, dict]:
        """
        Returns (data, meta)
        """
        request_name = self._url_to_request_name_label(url)
        with self.PROMETHEUS_HISTOGRAM.time() as t:
            try:
                response = self.session.get(
                    urljoin(self.host, url),
                    params=params,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if response.status_code != HTTPStatus.OK:
                    msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
                    logger.debug({'msg': msg})
                    raise NotOkResponse(msg, status=response.status_code, text=response.text)

                json_response = response.json()
                data = json_response['data']
                del json_response['data']
            except (KeyError, JSONDecodeError) as error:
                msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
                logger.debug({'msg': msg})
                raise error from error
            finally:
                t.labels(
                    name=request_name,
                    code=response.status_code,
                    domain=urlparse(self.host).netloc,
                )

        return data, json_response

    @abstractmethod
    def _url_to_request_name_label(self, url: str) -> str:
        """Remove all params from url and replace them with {param}"""
