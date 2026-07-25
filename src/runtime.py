from prometheus_client import start_http_server

from src import variables
from src.metrics.healthcheck_server import start_pulse_server
from src.metrics.logging import logging
from src.metrics.prometheus.basic import BUILD_INFO, ENV_VARIABLES_INFO
from src.services.deposit_signature_verification import bls_selfcheck
from src.utils.build import get_build_info


logger = logging.getLogger(__name__)


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

    log_bls_selfcheck()


def log_bls_selfcheck() -> None:
    try:
        result = bls_selfcheck()
    except Exception as error:  # pylint: disable=broad-except
        logger.error({'msg': 'BLS self-check failed to run.', 'error': repr(error)})
        return

    log = logger.info if result['ok'] else logger.error
    log({'msg': 'BLS deposit signature self-check.', **result})


def start_observability() -> None:
    logger.info({'msg': f'Start healthcheck server for Docker container on port {variables.HEALTHCHECK_SERVER_PORT}'})
    start_pulse_server()

    logger.info({'msg': f'Start http server with prometheus metrics on port {variables.PROMETHEUS_PORT}'})
    start_http_server(variables.PROMETHEUS_PORT)
