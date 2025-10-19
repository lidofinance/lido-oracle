from dataclasses import dataclass
from typing import Final, Tuple, Union, cast

import dag_cbor
from ipld_dag_pb import PBLink, PBNode, encode as dag_pb_encode
from multiformats import CID, multihash, varint

from .schemes import unixfs_pb2

BytesLike = Union[bytes, bytearray, memoryview]
Block = Tuple[CID, BytesLike]

CAR_VERSION = 1
DEFAULT_CHUNK_SIZE = 262144  # Default chunk size for IPFS UnixFS (256KB)
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

    def _chunk_data(self, data_bytes: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[bytes]:
        chunks = []
        for i in range(0, len(data_bytes), chunk_size):
            chunks.append(data_bytes[i:i + chunk_size])
        return chunks

    def _serialize_unixfs_leaf_node(self, data_bytes: bytes) -> bytes:
        """Serialize UnixFS leaf node (chunk) with rawLeaves: false behavior.

        Source: https://github.com/ipfs/js-ipfs-unixfs/blob/master/packages/ipfs-unixfs-importer/src/dag-builder/file.ts#L89-L96
        """
        unixfs = unixfs_pb2.Data()  # type: ignore[attr-defined]
        unixfs.Type = unixfs_pb2.Data.File  # type: ignore[attr-defined]
        unixfs.Data = data_bytes
        unixfs.filesize = len(data_bytes)
        unixfs_serialized = unixfs.SerializeToString()

        pb_node = PBNode(data=unixfs_serialized, links=[])
        return dag_pb_encode(pb_node)


    def _serialize_unixfs_parent_node(self, chunk_cids: list[CID], chunk_block_sizes: list[int], chunk_data_sizes: list[int], total_size: int) -> bytes:
        """Serialize UnixFS parent node that links to child chunks.

        Source: https://github.com/ipfs/js-ipfs-unixfs/blob/master/packages/ipfs-unixfs-importer/src/dag-builder/file.ts#L122-L186
        """
        # Create UnixFS data structure for parent file node
        unixfs = unixfs_pb2.Data()  # type: ignore[attr-defined]
        unixfs.Type = unixfs_pb2.Data.File  # type: ignore[attr-defined]

        # Add original chunk data sizes (not encoded block sizes) to UnixFS metadata
        for size in chunk_data_sizes:
            unixfs.blocksizes.append(size)

        # Calculate filesize as sum of blocksizes (matching JavaScript behavior)
        # Source: ipfs-unixfs fileSize() implementation
        unixfs.filesize = sum(chunk_data_sizes)

        unixfs_serialized = unixfs.SerializeToString()

        links = []
        for cid, block_size in zip(chunk_cids, chunk_block_sizes):
            links.append(PBLink(hash=cid, name="", size=block_size))

        pb_node = PBNode(data=unixfs_serialized, links=links)
        return dag_pb_encode(pb_node)

    def _create_cid_from_pb_node(self, pb_node_serialized: bytes) -> CID:
        root_digest = multihash.digest(pb_node_serialized, "sha2-256")
        return CID("base58btc", 0, "dag-pb", root_digest)

    def _build_unixfs_blocks_and_root(self, data_bytes: bytes) -> tuple[CID, list[Block]]:
        """Build UnixFS blocks and return root CID with all blocks.

        This method handles the common logic for both CID creation and CAR file generation.

        For files > DEFAULT_CHUNK_SIZE bytes, this chunks the data and creates a tree structure
        matching the JavaScript ipfs-unixfs-importer with rawLeaves: false.

        Returns:
            tuple: (root_cid, blocks) where blocks is a list of (CID, bytes) tuples
        """
        chunks = self._chunk_data(data_bytes)
        blocks = []

        if len(chunks) == 1:
            # Single chunk - create a simple UnixFS file node
            pb_node_serialized = self._serialize_unixfs_leaf_node(data_bytes)
            root_cid = self._create_cid_from_pb_node(pb_node_serialized)
            blocks = [(root_cid, pb_node_serialized)]
        else:
            # Multiple chunks - create leaf nodes for each chunk and a parent node
            chunk_cids = []
            chunk_block_sizes = []  # Size of the encoded DAG-PB blocks
            chunk_data_sizes = []   # Size of the original chunk data

            for chunk in chunks:
                # Create leaf node for each chunk
                leaf_node_serialized = self._serialize_unixfs_leaf_node(chunk)
                chunk_cid = self._create_cid_from_pb_node(leaf_node_serialized)
                chunk_cids.append(chunk_cid)
                # Track both the encoded block size and original data size
                chunk_block_sizes.append(len(leaf_node_serialized))
                chunk_data_sizes.append(len(chunk))
                # Add chunk block to blocks list
                blocks.append((chunk_cid, leaf_node_serialized))

            # Create parent node that links to all chunks
            parent_node_serialized = self._serialize_unixfs_parent_node(
                chunk_cids, chunk_block_sizes, chunk_data_sizes, len(data_bytes)
            )
            root_cid = self._create_cid_from_pb_node(parent_node_serialized)
            # Add parent block to blocks list
            blocks.append((root_cid, parent_node_serialized))

        return root_cid, blocks

    def create_unixfs_based_cid(self, data_bytes: bytes) -> str:
        root_cid, _ = self._build_unixfs_blocks_and_root(data_bytes)
        return root_cid.encode()

    def create_car_from_data(self, data_bytes: bytes) -> CarFile:
        root_cid, blocks = self._build_unixfs_blocks_and_root(data_bytes)

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
