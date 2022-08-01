import rlp
import requests
from eth_utils import decode_hex, to_canonical_address, to_bytes, to_int, to_hex, apply_key_map

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
    return (block_number, block_header_fields)


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


def normalize_address(x):
    return to_canonical_address(x)


def normalize_int(x):
    if isinstance(x, str) and not x.startswith("0x"):
        x = int(x)
    return to_int(hexstr=x) if isinstance(x, str) else to_int(x)


def to_0x_string(x):
    if isinstance(x, str) and not x.startswith("0x"):
        x = int(x)
    return to_hex(x)
