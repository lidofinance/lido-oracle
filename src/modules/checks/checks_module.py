import pytest


class ChecksModule:
    def execute_module(self):
        return pytest.main([
            'src/modules/checks/suites',
            '-c', 'src/modules/checks/pytest.ini',
        ])
