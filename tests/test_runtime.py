import logging

import pytest

from src import runtime, variables


@pytest.mark.unit
class TestLogStartup:
    def test_log_startup__private_variables__logged_masked(self, monkeypatch, caplog):
        monkeypatch.setattr(
            variables,
            'PRIVATE_ENV_VARS',
            {'EXECUTION_CLIENT_URI': ['https://rpc.example.com/v3/a1b2c3d4e5f6a7b8'], 'LIDO_IPFS_TOKEN': None},
        )

        with caplog.at_level(logging.INFO, logger=runtime.logger.name):
            runtime.log_startup('accounting')

        startup = next(record.msg for record in caplog.records if record.msg['msg'] == 'Oracle startup.')
        assert startup['variables']['module'] == 'accounting'
        assert startup['variables']['EXECUTION_CLIENT_URI'] == ['***']
        assert startup['variables']['LIDO_IPFS_TOKEN'] == ''
        for name, value in variables.PUBLIC_ENV_VARS.items():
            assert startup['variables'][name] == value
