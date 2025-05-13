import logging

import pytest

logger = logging.getLogger(__name__)


def execute_checks():
    logger.info({'msg': 'Check oracle is ready to work in the current environment.'})
    return pytest.main([
        'src/modules/checks/suites',
        '-c', 'src/modules/checks/pytest.ini',
    ])
