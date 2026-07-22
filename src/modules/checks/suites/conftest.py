import os
from unittest.mock import patch

import pytest
from _pytest._io import TerminalWriter
from xdist import is_xdist_controller  # type: ignore[import]
from xdist.dsession import TerminalDistReporter  # type: ignore[import]

from src import variables
from src.modules.oracles.common.runtime import build_staking_module_web3
from src.types import BlockRoot, EpochNumber, OracleModuleName, SlotNumber
from src.utils.api import opsgenie_api
from src.utils.blockstamp import build_blockstamp
from src.utils.slot import get_reference_blockstamp
from src.web3py.contract_tweak import tweak_w3_contracts
from src.web3py.extensions import (
    ConsensusClientModule,
    FallbackProviderModule,
    KeysAPIClientModule,
    LidoContracts,
    LidoValidatorsProvider,
    SignerModule,
    TelemetryDataBus,
    TransactionUtils,
)
from src.web3py.types import Web3


TITLE_PROPERTY_NAME = "test_title"

_config = None


@pytest.fixture()
def web3():
    """Basic web3 fixture without staking module contracts."""
    web3 = Web3(
        FallbackProviderModule(
            variables.EXECUTION_CLIENT_URI, request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION}
        )
    )
    tweak_w3_contracts(web3)
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)

    signer = SignerModule(
        web3,
        variables.ACCOUNT,
        variables.ACCOUNT_2,
        variables.DELEGATION_CONTRACT_ADDRESS,
    )
    telemetry_data_bus = TelemetryDataBus(
        variables.TELEMETRY_DATA_BUS_RPC,
        variables.DATA_BUS_ADDRESS,
        'checks',
        web3,
    )

    web3.attach_modules(
        {
            'lido_validators': LidoValidatorsProvider,
            'transaction': TransactionUtils,
            'signer': lambda: signer,
            'telemetry_data_bus': lambda: telemetry_data_bus,
            'cc': lambda: cc,  # type: ignore[dict-item]
            'kac': lambda: kac,  # type: ignore[dict-item]
        }
    )
    if variables.LIDO_LOCATOR_ADDRESS:
        web3.attach_modules({'lido_contracts': LidoContracts})

    return web3


@pytest.fixture()
def web3_cs_module():
    """Web3 fixture configured for CS module (reuses CSM entrypoint logic)."""
    module_address = os.getenv("CS_MODULE_ADDRESS")
    if not module_address:
        pytest.skip("CS_MODULE_ADDRESS is not set")
    with patch.object(variables, "STAKING_MODULE_ADDRESS", module_address):
        web3 = build_staking_module_web3(OracleModuleName.CHECK)
        return web3


@pytest.fixture()
def web3_curated_module():
    """Web3 fixture configured for Curated module (reuses CM entrypoint logic)."""
    module_address = os.getenv("CURATED_MODULE_ADDRESS")
    if not module_address:
        pytest.skip("CURATED_MODULE_ADDRESS is not set")
    with patch.object(variables, "STAKING_MODULE_ADDRESS", module_address):
        web3 = build_staking_module_web3(OracleModuleName.CHECK)
        return web3


@pytest.fixture(
    params=[
        pytest.param(0, id="Finalized blockstamp"),
        pytest.param(270, id="Blockstamp accounting frame ago"),
        pytest.param(
            6300,
            id="Blockstamp CSM frame ago",
            marks=pytest.mark.skipif(
                os.getenv("CS_MODULE_ADDRESS") is None and os.getenv("CURATED_MODULE_ADDRESS") is None,
                reason="Neither CS_MODULE_ADDRESS nor CURATED_MODULE_ADDRESS is set",
            ),
        ),
    ]
)
def blockstamp(web3, finalized_blockstamp, request):
    epochs_per_frame = request.param
    cc_config = web3.cc.get_config_spec()
    slots_per_frame = epochs_per_frame * cc_config.SLOTS_PER_EPOCH
    last_report_ref_slot = SlotNumber(finalized_blockstamp.slot_number - slots_per_frame)

    return get_reference_blockstamp(
        web3.cc,
        last_report_ref_slot,
        ref_epoch=EpochNumber(last_report_ref_slot // cc_config.SLOTS_PER_EPOCH),
        last_finalized_slot_number=finalized_blockstamp.slot_number,
    )


@pytest.fixture
def finalized_blockstamp(web3):
    block_root = BlockRoot(web3.cc.get_block_root('finalized').root)
    block_details = web3.cc.get_block_details(block_root)
    bs = build_blockstamp(block_details)
    cc_config = web3.cc.get_config_spec()
    return get_reference_blockstamp(
        web3.cc,
        bs.slot_number,
        ref_epoch=EpochNumber(bs.slot_number // cc_config.SLOTS_PER_EPOCH),
        last_finalized_slot_number=bs.slot_number,
    )


def pytest_collection_modifyitems(items):
    """Sort tests by finalized blockstamp first."""
    items.sort(key=lambda x: "Finalized blockstamp" in x.nodeid, reverse=True)


class CustomTerminal(TerminalDistReporter):
    def ensure_show_status(self):
        pass


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    global _config
    _config = config

    class SessionLike:
        config = None

    session_like = SessionLike()
    session_like.config = config
    if is_xdist_controller(session_like):  # type: ignore[arg-type]
        dsession = config.pluginmanager.getplugin("dsession")
        config.pluginmanager.unregister(dsession.trdist, "terminaldistreporter")

        custom_terminal = CustomTerminal(config)
        dsession.trdist = custom_terminal
        config.pluginmanager.register(custom_terminal)


def pytest_report_teststatus(report, config):
    def _skip_reason() -> str:
        longrepr = getattr(report, "longrepr", None)
        if isinstance(longrepr, tuple) and longrepr:
            return str(longrepr[-1])
        if longrepr:
            return str(longrepr)
        return "Skipped"

    if report.when == "setup" and report.skipped:
        return "skipped", _skip_reason(), "Skipped"
    if report.when == "call":
        if report.passed:
            return "passed", "✅ Checked", "✅ Checked"
        if report.failed:
            return "failed", "❌ Failed", "❌ Failed"
        if report.skipped:
            return "skipped", _skip_reason(), "Skipped"
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report) -> None:
    global _config  # pylint: disable=global-variable-not-assigned
    if _config is None:
        return

    class SessionLike:
        config = None

    session_like = SessionLike()
    session_like.config = _config

    if not is_xdist_controller(session_like):  # type: ignore[arg-type]
        return

    if report.when == 'setup' and not report.passed:
        print(report.head_line, end="")
    if report.when == 'call':
        print(report.head_line, end="")

        if report.failed:
            check_name = report.nodeid
            reason = str(report.longrepr) if report.longrepr else 'Unknown failure reason'
            opsgenie_api.send_opsgenie_alert(
                {
                    'message': f'Oracle check: {check_name}',
                    'description': f'Reason: {reason}',
                    'priority': opsgenie_api.AlertPriority.MINOR.value,
                    'tags': ['oracle_checks', 'oracle'],
                    'details': {'alertname': 'OracleDailyChecks'},
                }
            )

    if report.when == 'teardown':
        print()


def pytest_runtest_setup(item: pytest.Item):
    tw: TerminalWriter = item.config.pluginmanager.get_plugin("terminalreporter")._tw  # type: ignore  # pylint: disable=protected-access

    obj = getattr(item, "obj", None)
    parent = getattr(item.parent, "obj", None)

    module_doc = parent.__doc__
    if not module_doc or not obj:
        module_doc = f"Placeholder doc for parent of {item.nodeid}"

    check_doc = obj.__doc__
    if not check_doc or not parent:
        check_doc = f"Placeholder doc for {item.nodeid}"

    check_params = f"[{item.callspec.id}]" if hasattr(item, "callspec") else ""  # type: ignore[attr-defined]

    check_params_colorized = tw.markup(check_params, cyan=True)
    module_doc_colorized = tw.markup(f"[{module_doc}]", blue=True)
    message = f"{module_doc_colorized}{check_params_colorized} {check_doc}"
    item.user_properties.append((TITLE_PROPERTY_NAME, f">> {message}... "))
