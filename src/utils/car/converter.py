from typing import Final, Tuple, Union

import dag_cbor
from .schemes import merkledag_pb2, unixfs_pb2
from multiformats import CID, multihash, varint

BytesLike = Union[bytes, bytearray, memoryview]
Block = Tuple[CID, BytesLike]

CAR_VERSION = 1
BYTES_LIKE_TYPES: Final = (bytes, bytearray, memoryview)


class CAREncodingError(Exception):
    pass


class CARConverter:
    """CAR (Content Addressable aRchive) format converter."""
    
    def _encode_header(self, roots: list[CID]) -> bytes:
        try:
            header_data = {
                "version": CAR_VERSION,
                "roots": roots
            }
            header_bytes = dag_cbor.encode(header_data)
            header_len = varint.encode(len(header_bytes))
            return header_len + header_bytes
        except Exception as e:
            raise CAREncodingError(f"Failed to encode header: {e}") from e
    
    def _encode_block(self, cid: CID, block_bytes: BytesLike, block_index: int) -> bytes:
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
    
    def _encode(self, roots: list[CID], blocks: list[Block]) -> memoryview:
        if not isinstance(roots, list):
            raise TypeError("roots must be a list")
        if not isinstance(blocks, list):
            raise TypeError("blocks must be a list")
        if not roots:
            raise CAREncodingError("At least one root CID is required")
        
        buffer = bytearray()
        
        buffer.extend(self._encode_header(roots))
        
        for index, block in enumerate(blocks):
            if not isinstance(block, tuple) or len(block) != 2:
                raise CAREncodingError(f"Block {index}: must be a tuple of (CID, bytes)")
            
            cid, block_bytes = block
            buffer.extend(self._encode_block(cid, block_bytes, index))
        
        return memoryview(buffer)
    
    def _serialize_unixfs_file(self, data_bytes: bytes) -> bytes:
        """Serialize UnixFS Data for File using protobuf."""
        unixfs = unixfs_pb2.Data()
        unixfs.Type = unixfs_pb2.Data.File
        unixfs.Data = data_bytes
        unixfs.filesize = len(data_bytes)
        return unixfs.SerializeToString()
    
    def _serialize_dag_pb_node(self, unixfs_serialized: bytes) -> bytes:
        """Serialize DAG-PB PBNode using protobuf."""
        pb_node = merkledag_pb2.PBNode()
        pb_node.Data = unixfs_serialized
        return pb_node.SerializeToString()
    
    def create_car_from_data(self, data_bytes: bytes) -> Tuple[bytes, str, str, int]:
        """Create CAR archive from raw data."""
        unixfs_serialized = self._serialize_unixfs_file(data_bytes)
        pb_node_serialized = self._serialize_dag_pb_node(unixfs_serialized)

        # Create root CID as CIDv0 to match other providers
        root_digest = multihash.digest(pb_node_serialized, "sha2-256")
        root_cid = CID("base58btc", 0, "dag-pb", root_digest)

        blocks = [(root_cid, pb_node_serialized)]

        car = self._encode([root_cid], blocks)
        car_bytes = car.tobytes()

        # Create shard CID (CAR codec)
        car_digest = multihash.digest(car_bytes, "sha2-256")
        car_cid = CID("base58btc", 1, "car", car_digest)
        shard_cid = car_cid.encode('base58btc')

        size = len(car_bytes)

        return car_bytes, root_cid.encode(), shard_cid, size
