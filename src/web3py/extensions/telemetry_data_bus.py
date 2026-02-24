import json
import logging
from typing import cast

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from web3 import AsyncWeb3, Web3
from web3.module import Module

from src import variables, constants
from src.providers.execution.contracts.data_bus import DataBusContract
from src.utils.transaction import build_transaction_params, sign_and_send_transaction
from src.utils.version import get_oracle_version

logger = logging.getLogger(__name__)

EVENT_ID = Web3.keccak(text="OracleReport")


class TelemetryDataBus(Module):

    class MainnetForbiddenError(Exception):
        pass

    class ContractNotDeployedError(Exception):
        pass

    _data_bus_w3: Web3 | None
    _contract: DataBusContract | None

    def __init__(self, data_bus_rpc: str, data_bus_address: str, module_name: str, w3: AsyncWeb3 | Web3):
        super().__init__(w3)
        self._data_bus_w3 = None
        self._contract = None
        self._module_name = module_name

        if not data_bus_rpc or not data_bus_address:
            logger.warning({'msg': 'DataBus telemetry is not configured. Skipping initialization.'})
            return

        self._data_bus_w3 = self._create_web3(data_bus_rpc)
        address = Web3.to_checksum_address(data_bus_address)
        self._validate(address)
        self._contract = cast(DataBusContract, self._data_bus_w3.eth.contract(
            address=address,
            ContractFactoryClass=DataBusContract,
        ))

    @staticmethod
    def _create_web3(rpc_url: str) -> Web3:
        retry_strategy = Retry(
            total=3,
            status_forcelist=[418, 429, 500, 502, 503, 504],
            backoff_factor=1,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return Web3(Web3.HTTPProvider(
            rpc_url,
            request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
            session=session,
        ))

    def _validate(self, address: str) -> None:
        chain_id = self._data_bus_w3.eth.chain_id
        if chain_id == constants.MAINNET_CHAIN_ID:
            raise self.MainnetForbiddenError(
                f"DataBus telemetry must not be used on Ethereum Mainnet (chain_id={chain_id}) "
                "to prevent draining the report wallet."
            )

        code = self._data_bus_w3.eth.get_code(address)
        if not code:
            raise self.ContractNotDeployedError(
                f"No contract deployed at DataBus address {address} (chain_id={chain_id})."
            )

    def send_telemetry(self, report_data: tuple, report_hash: bytes) -> None:
        if self._contract is None:
            logger.warning({'msg': 'DataBus telemetry is not configured. Skipping send.'})
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
