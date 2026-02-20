import json
import logging

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.module import Module

from src import variables
from src.providers.execution.contracts.data_bus import DataBusContract
from src.utils.transaction import build_transaction_params, sign_and_send_transaction
from src.utils.version import get_oracle_version

logger = logging.getLogger(__name__)

EVENT_ID = Web3.keccak(text="OracleReport")


class TelemetryDataBus(Module):
    _data_bus_w3: Web3 | None
    _contract: DataBusContract | None

    def __init__(self, data_bus_rpc: str, data_bus_address: str, module_name: str):
        self._data_bus_w3 = None
        self._contract = None
        self._module_name = module_name

        if not data_bus_rpc or not data_bus_address:
            logger.warning({'msg': 'DataBus telemetry is not configured. Skipping initialization.'})
            return

        self._data_bus_w3 = Web3(Web3.HTTPProvider(data_bus_rpc))
        self._data_bus_w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        contract = self._data_bus_w3.eth.contract(
            address=Web3.to_checksum_address(data_bus_address),
            ContractFactoryClass=DataBusContract,
        )
        self._contract = contract  # type: ignore[assignment]

    @property
    def is_configured(self) -> bool:
        return self._data_bus_w3 is not None and self._contract is not None

    def send_telemetry(self, report_data: tuple, report_hash: bytes) -> None:
        if not self.is_configured:
            logger.warning({'msg': 'DataBus telemetry is not configured. Skipping send.'})
            return

        if not variables.ACCOUNT:
            logger.warning({'msg': 'No account configured. Skipping DataBus telemetry.'})
            return

        payload = json.dumps({
            'version': get_oracle_version(),
            'module': self._module_name,
            'report_hash': '0x' + report_hash.hex(),
            'report': list(report_data),
        }, default=str).encode('utf-8')

        tx = self._contract.send_message(EVENT_ID, payload)
        params = build_transaction_params(self._data_bus_w3, tx, variables.ACCOUNT)
        tx_hash = sign_and_send_transaction(self._data_bus_w3, tx, params, variables.ACCOUNT)
        logger.info({'msg': 'DataBus telemetry sent.', 'tx_hash': tx_hash.hex(), 'module': self._module_name})
