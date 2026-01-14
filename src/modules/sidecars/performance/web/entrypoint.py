from src.metrics.logging import logging
from src.modules.sidecars.performance.web.server import serve
from src.variables import PERFORMANCE_WEB_SERVER_API_PORT

logger = logging.getLogger(__name__)


def run() -> int:
    logger.info({'msg': f'Starting Performance Web Server on port {PERFORMANCE_WEB_SERVER_API_PORT}'})
    return serve()
