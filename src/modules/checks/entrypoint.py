import logging

from modules.checks.checks_module import ChecksModule


logger = logging.getLogger(__name__)


def run() -> int:
    logger.info({'msg': 'Check oracle is ready to work in the current environment.'})
    return ChecksModule().execute_module()
