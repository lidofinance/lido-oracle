from prometheus_client import start_http_server

from src import variables
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.metrics.prometheus.basic import BUILD_INFO, ENV_VARIABLES_INFO
from src.utils.build import get_build_info
from src.web3py.extensions import FallbackProviderModule


logger = logging.getLogger(__name__)


def build_execution_provider() -> FallbackProviderModule:
    logger.info({'msg': 'Initialize multi web3 provider.'})
    return FallbackProviderModule(
        variables.EXECUTION_CLIENT_URI,
        request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
        cache_allowed_requests=True,
    )


def log_startup(module_name: str) -> None:
    build_info = get_build_info()
    logger.info(
        {
            'msg': 'Oracle startup.',
            'variables': {
                **build_info,
                'module': module_name,
                **variables.PUBLIC_ENV_VARS,
            },
        }
    )
    ENV_VARIABLES_INFO.info(variables.PUBLIC_ENV_VARS)
    BUILD_INFO.info(build_info)


def start_observability() -> None:
    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)
