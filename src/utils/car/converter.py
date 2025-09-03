from dataclasses import dataclass
from typing import Final, Tuple, Union, cast

import dag_cbor
from .schemes import merkledag_pb2, unixfs_pb2
from multiformats import CID, multihash, varint

BytesLike = Union[bytes, bytearray, memoryview]
Block = Tuple[CID, BytesLike]

CAR_VERSION = 1
BYTES_LIKE_TYPES: Final = (bytes, bytearray, memoryview)


@dataclass
class CarFile:
    car_bytes: bytes
    root_cid: str
    shard_cid: str
    size: int


class CAREncodingError(Exception):
    pass


class CARConverter:
    """CAR (Content Addressable aRchive) format converter.

    Spec: https://ipld.io/specs/transport/car/carv1/

    """

    def _encode_header(self, roots: list[CID]) -> bytes:
        try:
            header_data = {
                "version": CAR_VERSION,
                "roots": roots
            }
            header_bytes = dag_cbor.encode(
                cast(dag_cbor.IPLDKind, header_data)
            )
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

    def _serialize_unixfs_pb_node(self, data_bytes: bytes) -> bytes:
        """Serialize UnixFS file data into DAG-PB node using protobuf.

        Specs:
        https://ipld.io/specs/codecs/dag-pb/spec/
        https://docs.ipfs.tech/concepts/file-systems/#unix-file-system-unixfs

        """
        # Create UnixFS data structure
        unixfs = unixfs_pb2.Data()  # type: ignore[attr-defined]
        unixfs.Type = unixfs_pb2.Data.File  # type: ignore[attr-defined]
        unixfs.Data = data_bytes
        unixfs.filesize = len(data_bytes)
        unixfs_serialized = unixfs.SerializeToString()

        # Wrap in DAG-PB node
        pb_node = merkledag_pb2.PBNode()  # type: ignore[attr-defined]
        pb_node.Data = unixfs_serialized
        return pb_node.SerializeToString()

    def _create_cid_from_pb_node(self, pb_node_serialized: bytes) -> CID:
        root_digest = multihash.digest(pb_node_serialized, "sha2-256")
        return CID("base58btc", 0, "dag-pb", root_digest)

    def create_unixfs_based_cid(self, data_bytes: bytes) -> str:
        pb_node_serialized = self._serialize_unixfs_pb_node(data_bytes)
        return self._create_cid_from_pb_node(pb_node_serialized).encode()

    def create_car_from_data(self, data_bytes: bytes) -> CarFile:
        pb_node_serialized = self._serialize_unixfs_pb_node(data_bytes)
        root_cid = self._create_cid_from_pb_node(pb_node_serialized)

        blocks = [(root_cid, pb_node_serialized)]

        car = self._encode([root_cid], blocks)
        car_bytes = car.tobytes()

        # Create shard CID (CAR codec)
        car_digest = multihash.digest(car_bytes, "sha2-256")
        car_cid = CID("base58btc", 1, "car", car_digest)
        shard_cid = car_cid.encode('base58btc')

        size = len(car_bytes)

        return CarFile(
            car_bytes=car_bytes,
            root_cid=root_cid.encode(),
            shard_cid=shard_cid,
            size=size
        )
