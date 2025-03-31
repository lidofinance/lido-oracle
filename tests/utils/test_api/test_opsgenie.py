import pytest
import logging
import requests
import responses
from unittest.mock import Mock

from src.utils.api.opsgenie import OpsGenieAPI


@pytest.fixture
def logger():
    return Mock(spec=logging.Logger)


@pytest.mark.unit
def test_send_opsgenie_alert__empty_credits__sending_skipped(logger):
    opsgenie_api = OpsGenieAPI(
        api_key='',
        api_url='',
        logger=logger,
    )

    opsgenie_api.send_opsgenie_alert({})

    logger.info.assert_called_with({'msg': 'OpsGenie not configured, ignore.'})
    logger.warning.assert_not_called()


@responses.activate
@pytest.mark.unit
def test_send_opsgenie_alert__not_empty_credits__sent_successfully(logger):
    opsgenie_api = OpsGenieAPI(
        api_key='test',
        api_url='https://api.testopsgenie.com',
        logger=logger,
    )
    response = responses.post('https://api.testopsgenie.com/v2/alerts', status=200)

    opsgenie_api.send_opsgenie_alert({})

    logger.info.assert_not_called()
    logger.warning.assert_not_called()
    assert response.call_count == 1


@responses.activate
@pytest.mark.unit
def test_send_opsgenie_alert__api_not_available__logged_warning(logger):
    opsgenie_api = OpsGenieAPI(
        api_key='test',
        api_url='https://api.testopsgenie.com',
        logger=logger,
    )
    response = responses.post('https://api.testopsgenie.com/v2/alerts', body=requests.RequestException())

    opsgenie_api.send_opsgenie_alert({})

    logger.info.assert_not_called()
    logger.warning.assert_called_with({'msg': f'OpsGenie is not available: {requests.RequestException()}.'})
    assert response.call_count == 1
