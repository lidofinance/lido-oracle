"""
References:
    https://github.com/ipfs/specs/blob/main/MERKLE_DAG.md
    https://github.com/ipfs/specs/blob/main/UNIXFS.md
    https://protobuf.dev/programming-guides/encoding/
"""

import hashlib
from itertools import batched

import multihash
from multiformats_cid.cid import make_cid
from py_ipfs_cid import compute_cid

CHUNKER_BLOCK_SIZE_BYTES = 256 * 1024
DAG_MAX_WIDTH = 174


def test_cid_from_lib():
    with open("./QmTN9oYsjcJjGMpRrT2PZD4iY6aJpy5aCSBvGKU2a9EMQF.json") as f:
        cid = compute_cid(f.read().encode())
        assert cid == "QmTN9oYsjcJjGMpRrT2PZD4iY6aJpy5aCSBvGKU2a9EMQF"


def test_cid_small_file():
    data = b"IPFS 8 my bytes\n"
    cid = get_cid(encode_small_filenode(data))
    assert str(cid) == compute_cid(data)


def test_cid_large_file():
    with open("./QmeRnRTw9jBn319oyKUo22c5K223sTfGyB9XNQ4zMDUUHV.json") as f:
        data = f.read().encode()
        cid = get_cid(encode_large_filenode(data))
        assert str(cid) == compute_cid(data)
        assert str(cid) == "QmeRnRTw9jBn319oyKUo22c5K223sTfGyB9XNQ4zMDUUHV"


def encode_small_filenode(data: bytes) -> bytes:
    assert len(data) <= CHUNKER_BLOCK_SIZE_BYTES

    body = b"\x08\x02" + b"\x12" + encode_varint(len(data)) + data + b"\x18" + encode_varint(len(data))
    body = b"\x0a" + encode_varint(len(body)) + body
    return body


def encode_large_filenode(data: bytes) -> bytes:
    assert len(data) <= DAG_MAX_WIDTH * CHUNKER_BLOCK_SIZE_BYTES
    assert len(data) > CHUNKER_BLOCK_SIZE_BYTES

    childs = []

    for chunk in batched(data, CHUNKER_BLOCK_SIZE_BYTES):
        chunk_bytes = b"".join(map(int.to_bytes, chunk))
        print(f"len(chunk)={len(chunk_bytes)}")
        encoded = encode_small_filenode(chunk_bytes)
        childs.append((encoded, len(chunk_bytes)))
        print(get_cid(encoded))

    # 12 2a (2:LEN 42) (Links[0])
    # 0a 22 ??? (2:LEN) (TODO)
    # 12 20 616359aa9a3e490219421bd537a912ba06761ea03924e3de28d0798ced2db21d (2:LEN hash)
    # 12 00 (2:LEN Name: "")
    # 18 8e 80 10 (3:VARINT 262158)
    # 12 2a (2:LEN 42) (Links[1])
    # 0a 22 ??? (1:LEN) (TODO)
    # 12 20 f67e37efad98435807e003339f41bdd8e7add213bd786283a0c79d836aa10a8a (hash)
    # 12 00 (2:LEN Name: "")
    # 18 e7 a8 0e (3:VARINT 234599)
    # 0a 0e (2:LEN) ??? (TODO)
    # 08 02 (Type: File)
    # 18 d9 a8 1e (496729)
    # 20 80 80 10 (blocksized[0])
    # 20 d9 a8 0e (blocksizes[1])

    body = b""

    for encoded, _ in childs:
        body += encode_link(encoded)

    body = body + b"\x0a\x0e" + b"\x08\x02" + b"\x18" + encode_varint(len(data))

    for _, size in childs:
        body += b"\x20" + encode_varint(size)

    return body


def encode_link(encoded: bytes):
    hash = hashlib.sha256(encoded).digest()
    body = b"\x0a\x22" + b"\x12\x20" + hash + b"\x12\x00" + b"\x18" + encode_varint(len(encoded))
    return b"\x12" + len(body).to_bytes() + body


def get_cid(input: bytes):
    digest = hashlib.sha256(input).digest()
    multihash_value = multihash.encode(digest, "sha2-256")
    return make_cid(0, "dag-pb", multihash_value)


def encode_varint(v: int) -> bytes:
    out = b""

    while v > 0x7F:
        buf = v & 0x7F | 0x80
        out += buf.to_bytes()
        v >>= 7

    return out + v.to_bytes()
