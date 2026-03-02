import pytest


class ChecksModule:
    """
    Module that executes all tests to figure out that environment is ready for Oracle.

    Checks:
        - Consensus Layer node
        - Execution Layer node
        - Keys API service
    if LIDO_LOCATOR address provided
        - Checks configs in Accounting module and Ejector module
    if CS_MODULE_ADDRESS and CURATED_MODULE_ADDRESS provided
        - Checks configs in Staking Module oracle module
        - Checks with special blockstamp value (6300 slots in the past)
    """

    def execute_module(self):
        return pytest.main(
            [
                'src/modules/checks/suites',
                '-c',
                'src/modules/checks/pytest.ini',
            ]
        )
