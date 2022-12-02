import logging

from hexbytes import HexBytes
from web3 import Web3

from src.contracts import contracts
from src.modules.interface import OracleModule
from src.providers.execution import check_transaction, sign_and_send_transaction
from src.providers.typings import SlotNumber
from src.variables import ACCOUNT, GAS_LIMIT

logger = logging.getLogger(__name__)


class StethPriceBalancer(OracleModule):
    def __init__(self, web3: Web3):
        logger.info({'msg': 'Initialize Oracle STETH Price Balancer Module.'})

        self._w3 = web3

    def run_module(self, slot: SlotNumber, block_hash: HexBytes):
        logging.info({'msg': 'Run STETH price balancer.'})

        oracle_price = contracts.merkle_price_oracle.functions.stethPrice().call(block_identifier=block_hash)
        pool_price = contracts.pool.functions.get_dy(1, 0, 10**18).call(block_identifier=block_hash)

        percentage_diff = 100 * abs(1 - oracle_price / pool_price)

        logging.info(
            f'StETH stats: (pool price - {pool_price / 1e18:.6f}, oracle price - {oracle_price / 1e18:.6f}, difference - {percentage_diff:.2f}%)'
        )

        proof_params = contracts.merkle_price_oracle.functions.getProofParams().call(block_identifier=block_hash)

        # proof_params[-1] contains priceUpdateThreshold value in basis points: 10000 BP equal to 100%, 100 BP to 1%.
        price_update_threshold = proof_params[-1] / 100
        is_state_actual = percentage_diff < price_update_threshold

        if is_state_actual:
            logging.info(
                f'StETH Price Oracle state valid (prices difference < {price_update_threshold:.2f}%). No update required.'
            )
            return

        logging.info(
            f'StETH Price Oracle state outdated (prices difference >= {price_update_threshold:.2f}%). Submiting new one...'
        )

        header_blob, proofs_blob = encode_proof_data(provider, block_number, proof_params)

        pending_block = self._w3.eth.get_block('pending')

        tx = contracts.merkle_price_oracle.functions.submitState(header_blob, proofs_blob).buildTransaction(
            {
                'from': ACCOUNT.address,
                'gas': GAS_LIMIT,
                'maxFeePerGas': pending_block.baseFeePerGas * 2 + self._w3.eth.max_priority_fee * 2,
                'maxPriorityFeePerGas': self._w3.eth.max_priority_fee * 2,
                "nonce": self._w3.eth.get_transaction_count(ACCOUNT.address),
            }
        )

        if check_transaction(tx):
            sign_and_send_transaction(self._w3, tx, ACCOUNT)


# ------------------------------TODO review--------------------------------------------------------------
import rlp
import requests
from eth_utils import decode_hex, to_bytes, to_int, to_hex, apply_key_map

BLOCK_HEADER_FIELDS = [
    "parentHash",
    "sha3Uncles",
    "miner",
    "stateRoot",
    "transactionsRoot",
    "receiptsRoot",
    "logsBloom",
    "difficulty",
    "number",
    "gasLimit",
    "gasUsed",
    "timestamp",
    "extraData",
    "mixHash",
    "nonce",
]


def encode_proof_data(provider, block_number, proof_params):
    block_number = block_number if block_number == "latest" or block_number == "earliest" else hex(int(block_number))

    (block_number, block_header) = request_block_header(
        provider=provider,
        block_number=block_number,
    )

    (pool_acct_proof, pool_storage_proofs) = request_account_proof(
        provider=provider,
        block_number=block_number,
        address=proof_params[0],
        slots=proof_params[2:4],
    )

    (steth_acct_proof, steth_storage_proofs) = request_account_proof(
        provider=provider,
        block_number=block_number,
        address=proof_params[1],
        slots=proof_params[4:10],
    )

    header_blob = rlp.encode(block_header)

    proofs_blob = rlp.encode([pool_acct_proof, steth_acct_proof] + pool_storage_proofs + steth_storage_proofs)

    return (header_blob, proofs_blob)


def request_block_header(provider, block_number):
    r = provider.make_request("eth_getBlockByNumber", params=[block_number, True])

    block_dict = get_json_rpc_result(r)
    block_number = normalize_int(block_dict["number"])

    if "proofOfAuthorityData" in block_dict:
        block_dict = dict(apply_key_map({'proofOfAuthorityData': 'extraData'}, block_dict))

    block_header_fields = [normalize_bytes(block_dict[f]) for f in BLOCK_HEADER_FIELDS]
    return block_number, block_header_fields


def request_account_proof(provider, block_number, address, slots):
    hex_slots = [to_0x_string(s) for s in slots]
    r = provider.make_request("eth_getProof", params=[address.lower(), hex_slots, to_0x_string(block_number)])

    result = get_json_rpc_result(r)

    account_proof = decode_rpc_proof(result["accountProof"])
    storage_proofs = [decode_rpc_proof(slot_data["proof"]) for slot_data in result["storageProof"]]

    return (account_proof, storage_proofs)


def decode_rpc_proof(proof_data):
    return [rlp.decode(decode_hex(node)) for node in proof_data]


def get_json_rpc_result(response):
    if "error" in response:
        raise requests.RequestException(
            f"RPC error { response['error']['code'] }: { response['error']['message'] }", response=response
        )
    return response["result"]


def normalize_bytes(x):
    return to_bytes(hexstr=x) if isinstance(x, str) else to_bytes(x)


def normalize_int(x):
    if isinstance(x, str) and not x.startswith("0x"):
        x = int(x)
    return to_int(hexstr=x) if isinstance(x, str) else to_int(x)


def to_0x_string(x):
    if isinstance(x, str) and not x.startswith("0x"):
        x = int(x)
    return to_hex(x)
