import dag_cbor
from dag_cbor import IPLDKind
from multiformats import CID, varint, multihash
from typing import Final, Tuple, Union

from car.schemes import unixfs_pb2, merkledag_pb2

BytesLike = Union[bytes, bytearray, memoryview]
Block = Tuple[CID, BytesLike]

CAR_VERSION = 1
BYTES_LIKE_TYPES: Final = (bytes, bytearray, memoryview)


class CAREncodingError(Exception):
    pass


def _encode_car_header(roots: list[CID]) -> bytes:
    try:
        header_data = {
            "version": CAR_VERSION,
            "roots": list[IPLDKind](roots)
        }
        header_bytes = dag_cbor.encode(header_data)
        header_len = varint.encode(len(header_bytes))
        return header_len + header_bytes
    except Exception as e:
        raise CAREncodingError(f"Failed to encode header: {e}") from e


def _encode_car_block(cid: CID, block_bytes: BytesLike, block_index: int) -> bytes:
    if not isinstance(cid, CID):
        raise CAREncodingError(f"Block {block_index}: CID must be an instance of CID, got {type(cid)}")
    
    if not isinstance(block_bytes, BYTES_LIKE_TYPES):
        raise CAREncodingError(
            f"Block {block_index}: block bytes must be bytes-like, got {type(block_bytes)}"
        )
    
    try:
        cid_bytes = bytes(cid)
        total_length = len(cid_bytes) + len(block_bytes)
        block_len = varint.encode(total_length)
        return block_len + cid_bytes + block_bytes
    except Exception as e:
        raise CAREncodingError(f"Failed to encode block {block_index}: {e}") from e


def encode_as_car(roots: list[CID], blocks: list[Block]) -> memoryview:
    """Encode data as CAR (Content Addressable aRchive) format.
    
    Implements CAR v1 specification: https://ipld.io/specs/transport/car/carv1/
    
    Args:
        roots: List of root CIDs that represent entry points to the data
        blocks: List of (CID, bytes) tuples representing IPLD blocks
        
    Returns:
        Memory view of the encoded CAR data
        
    """
    if not isinstance(roots, list):
        raise TypeError("roots must be a list")
    if not isinstance(blocks, list):
        raise TypeError("blocks must be a list")
    if not roots:
        raise CAREncodingError("At least one root CID is required")
    
    buffer = bytearray()
    
    buffer.extend(_encode_car_header(roots))
    
    for index, block in enumerate(blocks):
        if not isinstance(block, tuple) or len(block) != 2:
            raise CAREncodingError(f"Block {index}: must be a tuple of (CID, bytes)")
        
        cid, block_bytes = block
        buffer.extend(_encode_car_block(cid, block_bytes, index))
    
    return memoryview(buffer)


def serialize_unixfs_file(data_bytes):
    """Serialize UnixFS Data for File (Type=2, no chunks) using protobuf."""
    unixfs = unixfs_pb2.Data()
    unixfs.Type = unixfs_pb2.Data.File  # Type = 2
    unixfs.Data = data_bytes
    unixfs.filesize = len(data_bytes)
    return unixfs.SerializeToString()

def serialize_dag_pb_node(unixfs_serialized):
    """Serialize DAG-PB PBNode (Data only, no Links) using protobuf."""
    pb_node = merkledag_pb2.PBNode()
    pb_node.Data = unixfs_serialized
    return pb_node.SerializeToString()

def create_car_from_data(data_bytes):
    unixfs_serialized = serialize_unixfs_file(data_bytes)
    pb_node_serialized = serialize_dag_pb_node(unixfs_serialized)

    # Create root CID as CIDv0 to match other providers
    root_digest = multihash.digest(pb_node_serialized, "sha2-256")
    root_cid = CID("base58btc", 0, "dag-pb", root_digest)

    blocks = [(root_cid, pb_node_serialized)]

    car = encode_as_car([root_cid], blocks)
    car_bytes = car.tobytes()

    # Create shard CID (CAR codec)
    car_digest = multihash.digest(car_bytes, "sha2-256")
    car_cid = CID("base58btc", 1, "car", car_digest)
    shard_cid = car_cid.encode('base58btc')

    size = len(car_bytes)

    return car_bytes, root_cid.encode(), shard_cid, size
