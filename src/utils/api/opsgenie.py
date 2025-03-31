import functools

import requests
import logging
from enum import Enum

from src import variables


class OpsGenieAPI:

    class AlertPriority(Enum):
        SHOW_STOPPER = 'P1'
        CRITICAL = 'P2'
        MAJOR = 'P3'
        MINOR = 'P4'
        INFO = 'P5'

    def __init__(
        self,
        api_key: str,
        api_url: str,
        logger: logging.Logger,
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.logger = logger

    def send_opsgenie_alert(
        self,
        payload: dict,
    ) -> None:
        """ Payload fields

        https://docs.opsgenie.com/docs/alert-api#create-alert

        """
        if not self.api_key or not self.api_url:
            self.logger.info({'msg': 'OpsGenie not configured, ignore.'})
            return

        headers = {
            'Authorization': f'GenieKey {self.api_key}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(
                f'{self.api_url}/v2/alerts',
                json=payload,
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            self.logger.warning(
                {'msg': f'OpsGenie is not available: {e}.'}
            )


@functools.lru_cache(maxsize=1)
def opsgenie_api_factory():
    logger = logging.getLogger(__name__)
    return OpsGenieAPI(
        api_key=variables.OPSGENIE_API_KEY,
        api_url=variables.OPSGENIE_API_URL,
        logger=logger,
    )


opsgenie_api = opsgenie_api_factory()
