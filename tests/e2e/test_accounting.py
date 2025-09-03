import pytest

from src.modules.accounting.accounting import Accounting
from tests.e2e.conftest import wait_for_message_appeared


@pytest.mark.e2e
def test_app(start_accounting, caplog):
    wait_for_message_appeared(caplog, "{'msg': 'Run module as daemon.'}", timeout=10)
    wait_for_message_appeared(caplog, "{'msg': 'Check if main data was submitted.', 'value': False}")
    wait_for_message_appeared(caplog, "{'msg': 'Check if contract could accept report.', 'value': True}")
    wait_for_message_appeared(caplog, "{'msg': 'Execute module.'}")
    wait_for_message_appeared(caplog, "{'msg': 'Checking bunker mode'}", timeout=1800)
    wait_for_message_appeared(
        caplog, f"{'msg': 'Send report hash. Consensus version: [{Accounting.COMPATIBLE_CONSENSUS_VERSION}]'}"
    )
