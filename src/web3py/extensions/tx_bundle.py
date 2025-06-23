import json
import logging
import time

import requests
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_typing import HexStr
from web3.contract.contract import ContractFunction
from web3.types import Wei, Nonce

from src import variables
from src.web3py.types import Web3

logger = logging.getLogger(__name__)


class TransactionBundle:
    @staticmethod
    def send_tx_bundle(w3: Web3, txs: list[ContractFunction]):
        """Reverts if sees no bundle onchain"""
        if variables.ACCOUNT:
            signed_txs = TransactionBundle._sign_transactions(w3, txs)
            TransactionBundle._send_bundle(w3, signed_txs)
        else:
            logger.info({'msg': 'No account provided. Dry mode'})

    @staticmethod
    def _sign_transactions(w3: Web3, txs: list[ContractFunction]) -> list[HexStr]:
        nonce = w3.eth.get_transaction_count(variables.ACCOUNT.address)  # type: ignore[union-attr]
        latest = w3.eth.get_block('latest')

        signed_txs = []

        max_priority_fee = Wei(
            min(
                variables.MAX_PRIORITY_FEE,
                max(
                    # Increase priority for private bundle
                    w3.eth.fee_history(1, 'latest', [variables.PRIORITY_FEE_PERCENTILE])['reward'][0][0],
                    variables.MIN_PRIORITY_FEE,
                )
            )
        )

        for tx in txs:
            tx_params = tx.build_transaction({
                "maxFeePerGas": Wei(latest["baseFeePerGas"] * 2 + max_priority_fee),
                "maxPriorityFeePerGas": max_priority_fee,
                'gas': variables.BUNDLE_GAS_LIMIT_FOR_EACH_TX,
                'nonce': nonce,
            })
            nonce = Nonce(nonce + 1)
            signed_tx = w3.eth.account.sign_transaction(tx_params, variables.ACCOUNT.key)  # type: ignore[union-attr]

            signed_txs.append(signed_tx.rawTransaction.hex())

        return signed_txs

    @staticmethod
    def _send_bundle(w3: Web3, signed_txs: list[HexStr]):
        current_block = w3.eth.block_number
        blocks_count = 6

        TransactionBundle._send_payload(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_sendBundle",
                "params": [{
                    "txs": signed_txs,  # can be a list of multiple txs
                }],
            },
            range(current_block + 1, current_block + blocks_count + 1),
        )

        time.sleep(blocks_count * 12 / 2)

    @staticmethod
    def _send_payload(payload: dict, block_range: range):
        head_signer = Account.create()  # pylint: disable=no-value-for-parameter

        for block_num in block_range:
            for relay in variables.PRIVATE_RELAYS_LIST:
                payload['params'][0]['blockNumber'] = hex(block_num)

                payload_j = json.dumps(payload)

                msg = encode_defunct(text=Web3.keccak(text=payload_j).hex())

                signature = head_signer.sign_message(msg).signature.hex()
                headers = {
                    'Content-Type': 'application/json',
                    'X-Flashbots-Signature': f"{head_signer.address}:{signature}"
                }
                try:
                    # Small timeout to be slow relay response won't affect other requests
                    response = requests.post(relay, headers=headers, data=payload_j, timeout=2)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error({
                        'msg': 'Failed to send payload.',
                        'relay': relay,
                        'value': repr(e),
                        'block_number': payload['params'][0]['blockNumber'],
                    })
                else:
                    logger.info({
                        'msg': 'Sent bundle to relay.',
                        'relay': relay,
                        'value': response.text,
                        'block_number': payload['params'][0]['blockNumber'],
                    })
