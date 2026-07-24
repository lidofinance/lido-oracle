import json
import logging
import time
from enum import Enum
from typing import cast

from eth_account.signers.local import LocalAccount
from hexbytes import HexBytes
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from web3 import AsyncWeb3, Web3
from web3.contract.contract import ContractFunction
from web3.module import Module

from src import variables
from src.metrics.prometheus.basic import TELEMETRY_ACCOUNT_BALANCE
from src.providers.execution.contracts.data_bus import DataBusContract
from src.utils.transaction import build_transaction_params, sign_and_send_transaction
from src.utils.version import get_oracle_version


logger = logging.getLogger(__name__)

# Interval between transaction status polls while waiting for inclusion or a nonce change.
_POLL_INTERVAL_SECONDS = 12


class TelemetryEventId(Enum):
    ORACLE_REPORT = Web3.keccak(text="OracleReport")
    ORACLE_STARTUP = Web3.keccak(text="OracleStartup")
    DIAGNOSTIC = Web3.keccak(text="Diagnostic")


class TelemetryDataBus(Module):
    class ContractNotDeployedError(Exception):
        pass

    class SendTimeoutError(Exception):
        pass

    _data_bus_w3: Web3 | None
    _contract: DataBusContract | None

    def __init__(self, data_bus_rpc: str, data_bus_address: str, module_name: str, w3: AsyncWeb3 | Web3):
        super().__init__(w3)
        self._data_bus_w3 = None
        self._contract = None
        self._module_name = module_name
        self._chain_id = w3.eth.chain_id

        if not data_bus_rpc or not data_bus_address:
            logger.warning({'msg': 'DataBus telemetry is not configured. Skipping initialization.'})
            return

        self._data_bus_w3 = self._create_web3(data_bus_rpc)
        address = Web3.to_checksum_address(data_bus_address)
        self._validate(address)
        self._contract = cast(
            DataBusContract,
            self._data_bus_w3.eth.contract(
                address=address,
                ContractFactoryClass=DataBusContract,
            ),
        )

    def _create_web3(self, rpc_url: str) -> Web3:
        retry_strategy = Retry(
            total=3,
            status_forcelist=[418, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"],
            backoff_factor=1,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return Web3(
            Web3.HTTPProvider(
                rpc_url,
                request_kwargs={'timeout': variables.HTTP_REQUEST_TIMEOUT_EXECUTION},
                session=session,
            )
        )

    def _validate(self, address: str) -> None:
        if self._data_bus_w3 is None:
            raise RuntimeError("DataBus Web3 instance is not initialized.")

        chain_id = self._data_bus_w3.eth.chain_id
        code = self._data_bus_w3.eth.get_code(Web3.to_checksum_address(address))
        if not code:
            raise self.ContractNotDeployedError(
                f"No contract deployed at DataBus address {address} (chain_id={chain_id})."
            )

    def update_telemetry_account_balance_metric(self) -> None:
        if self._data_bus_w3 is None or variables.TELEMETRY_ACCOUNT is None:
            return

        balance = self._data_bus_w3.eth.get_balance(variables.TELEMETRY_ACCOUNT.address)
        TELEMETRY_ACCOUNT_BALANCE.labels(address=variables.TELEMETRY_ACCOUNT.address).set(balance)

    def send_telemetry(self, event_id: TelemetryEventId, data: dict | None = None) -> None:
        if self._contract is None or self._data_bus_w3 is None:
            logger.warning({'msg': 'DataBus telemetry is not configured. Skipping send.'})
            return

        if variables.TELEMETRY_ACCOUNT is None:
            logger.warning({'msg': 'No account provided. Skipping telemetry send.'})
            return

        message: dict = {
            'chain_id': self._chain_id,
            'version': get_oracle_version(),
            'module': self._module_name,
        }
        if data:
            message['data'] = data
        payload = json.dumps(message, default=str).encode('utf-8')

        tx = self._contract.send_message(event_id.value, payload)
        tx_hash = self._send_with_retry(tx, self._data_bus_w3, variables.TELEMETRY_ACCOUNT)
        logger.info({'msg': 'DataBus telemetry sent.', 'tx_hash': tx_hash.hex(), 'module': self._module_name})

        self.update_telemetry_account_balance_metric()

    def _send_with_retry(self, tx: ContractFunction, w3: Web3, account: LocalAccount) -> bytes:
        deadline = time.monotonic() + variables.TELEMETRY_TX_SEND_TIMEOUT_SECONDS
        attempt = 0
        tx_hash: bytes | None = None
        nonce: int | None = None

        while time.monotonic() < deadline:
            attempt += 1
            try:
                if tx_hash is not None:
                    sent_tx = w3.eth.get_transaction(HexBytes(tx_hash))
                    if sent_tx.get('blockNumber') is not None:
                        return tx_hash

                    current_nonce = w3.eth.get_transaction_count(account.address)
                    if current_nonce == nonce:
                        remaining = deadline - time.monotonic()
                        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))
                        continue

                params = build_transaction_params(w3, tx, account)
                nonce = params.get('nonce')
                tx_hash = sign_and_send_transaction(w3, tx, params, account)
            except Exception as error:  # pylint: disable=broad-exception-caught
                remaining = deadline - time.monotonic()
                logger.warning(
                    {
                        'msg': 'Failed to send DataBus telemetry transaction. Will retry.',
                        'attempt': attempt,
                        'remaining_seconds': max(remaining, 0),
                        'error': str(error),
                    }
                )
                if remaining <= 0:
                    break
                time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))
