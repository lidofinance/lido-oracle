import logging
from abc import ABC
from http import HTTPStatus
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

from prometheus_client import Counter, Histogram
from requests import JSONDecodeError, Session
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
    PROMETHEUS_COUNTER: Counter

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
        with self.PROMETHEUS_HISTOGRAM.time():
            response = self.session.get(
                urljoin(self.host, url),
                params=params,
                timeout=self.REQUEST_TIMEOUT,
            )

        if response.status_code != HTTPStatus.OK:
            msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
            logger.debug({'msg': msg})
            raise NotOkResponse(msg, status=response.status_code, text=response.text)

        try:
            json_response = response.json()
            if 'data' in json_response:
                data = json_response['data']
                del json_response['data']
                meta = json_response
            else:
                data = json_response
                meta = {}
        except (KeyError, JSONDecodeError) as error:
            msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
            logger.debug({'msg': msg})
            raise error from error
        finally:
            self.PROMETHEUS_COUNTER.labels(
                method='get',
                code=response.status_code,
                domain=urlparse(self.host).netloc,
            ).inc()

        return data, meta
