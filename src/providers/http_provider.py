import logging
from abc import ABC
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

from requests import Session, JSONDecodeError
from requests.adapters import HTTPAdapter
from urllib3 import Retry


logger = logging.getLogger(__name__)


class HTTPProvider(ABC):
    REQUEST_TIMEOUT = 300

    PROMETHEUS_HISTOGRAM = None
    PROMETHEUS_COUNTER = None

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

        try:
            json_response = response.json()
            data = json_response['data']
            del json_response['data']
        except (KeyError, JSONDecodeError) as error:
            msg = f'Response [{response.status_code}] with text: "{str(response.text)}" returned.'
            logger.error(msg)
            raise error from error
        finally:
            self.PROMETHEUS_COUNTER.labels(
                method='get',
                code=response.status_code,
                domain=urlparse(self.host).netloc,
            ).inc()

        return data, json_response
