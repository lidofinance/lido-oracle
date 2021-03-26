import math
import json

from ethereum import block, utils
import rlp


def encode_proof_data(provider, block_number, proof_params):
    block_number = block_number if block_number == "latest" or block_number == "earliest" else hex(int(block_number))

    block_header = request_block_header(
        provider=provider,
        block_number=block_number,
    )

    (pool_acct_proof, pool_storage_proofs) = request_account_proof(
        provider=provider,
        block_number=block_header.number,
        address=proof_params[0],
        slots=proof_params[2:4],
    )

    (steth_acct_proof, steth_storage_proofs) = request_account_proof(
        provider=provider,
        block_number=block_header.number,
        address=proof_params[1],
        slots=proof_params[4:11],
    )

    header_blob = rlp.encode(block_header)

    proofs_blob = rlp.encode([pool_acct_proof, steth_acct_proof] + pool_storage_proofs + steth_storage_proofs)
    return (header_blob, proofs_blob)


def request_block_header(provider, block_number):
    r = provider.make_request("eth_getBlockByNumber", params=[block_number, True])
    block_dict = r["result"]

    header = block.BlockHeader(
        normalize_bytes(block_dict["parentHash"]),
        normalize_bytes(block_dict["sha3Uncles"]),
        utils.normalize_address(block_dict["miner"]),
        normalize_bytes(block_dict["stateRoot"]),
        normalize_bytes(block_dict["transactionsRoot"]),
        normalize_bytes(block_dict["receiptsRoot"]),
        utils.bytes_to_int(normalize_bytes(block_dict["logsBloom"])),
        utils.parse_as_int(block_dict["difficulty"]),
        utils.parse_as_int(block_dict["number"]),
        utils.parse_as_int(block_dict["gasLimit"]),
        utils.parse_as_int(block_dict["gasUsed"]),
        utils.parse_as_int(block_dict["timestamp"]),
        normalize_bytes(block_dict["extraData"]),
        normalize_bytes(block_dict["mixHash"]),
        normalize_bytes(block_dict["nonce"]),
    )

    if normalize_bytes(block_dict["hash"]) != header.hash:
        raise ValueError(
            """Blockhash does not match.
            Received invalid block header? {} vs {}""".format(
                str(normalize_bytes(block_dict["hash"])), str(header.hash)
            )
        )

    return header


def request_account_proof(provider, block_number, address, slots):
    hex_slots = [to_0x_string(s) for s in slots]

    r = provider.make_request(
        method="eth_getProof",
        params=[address.lower(), hex_slots, to_0x_string(block_number)],
    )

    result = r["result"]

    account_proof = decode_rpc_proof(result["accountProof"])
    storage_proofs = [decode_rpc_proof(slot_data["proof"]) for slot_data in result["storageProof"]]

    return (account_proof, storage_proofs)


def decode_rpc_proof(proof_data):
    return [rlp.decode(utils.decode_hex(node)) for node in proof_data]


def normalize_bytes(hash):
    if isinstance(hash, str):
        if hash.startswith("0x"):
            hash = hash[2:]
        if len(hash) % 2 != 0:
            hash = "0" + hash
        return utils.decode_hex(hash)
    elif isinstance(hash, int):
        return hash.to_bytes(length=(math.ceil(hash.bit_length() / 8)), byteorder="big", signed=False)


def to_0x_string(v):
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, str):
        return v if v.startswith("0x") else hex(int(v))
    return hex(v)
