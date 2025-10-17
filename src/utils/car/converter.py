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

    def _chunk_data(self, data_bytes: bytes, chunk_size: int = 262144) -> list[bytes]:
        """Chunk data into fixed-size pieces (matching ipfs-unixfs-importer behavior)."""
        if len(data_bytes) <= chunk_size:
            return [data_bytes]

        chunks = []
        offset = 0
        while offset < len(data_bytes):
            chunk = data_bytes[offset:offset + chunk_size]
            chunks.append(chunk)
            offset += chunk_size
        return chunks

    def _serialize_unixfs_leaf_node(self, data_bytes: bytes) -> bytes:
        """Serialize UnixFS leaf node (chunk) with rawLeaves: false behavior."""
        # Create UnixFS data structure for a file chunk
        unixfs = unixfs_pb2.Data()  # type: ignore[attr-defined]
        unixfs.Type = unixfs_pb2.Data.File  # type: ignore[attr-defined]
        unixfs.Data = data_bytes
        unixfs.filesize = len(data_bytes)
        unixfs_serialized = unixfs.SerializeToString()

        # Wrap in DAG-PB node
        pb_node = merkledag_pb2.PBNode()  # type: ignore[attr-defined]
        pb_node.Data = unixfs_serialized
        return pb_node.SerializeToString()

    def _js_encode_varint(self, value: int) -> bytes:
        """Encode varint same as JavaScript implementation"""
        result = bytearray()
        while value >= 128:
            result.append((value & 0x7f) | 0x80)
            value >>= 7
        result.append(value)
        return bytes(result)

    def _js_sov(self, x: int) -> int:
        """Calculate size of varint (JavaScript sov function)"""
        if x % 2 == 0:
            x += 1
        return (self._js_len64(x) + 6) // 7

    def _js_len64(self, x: int) -> int:
        """JavaScript len64 function"""
        n = 0
        if x >= 2**32:
            x = x // 2**32
            n = 32
        if x >= (1 << 16):
            x >>= 16
            n += 16
        if x >= (1 << 8):
            x >>= 8
            n += 8
        # simplified len8tab lookup
        return n + (8 if x >= 128 else 7 if x >= 64 else 6 if x >= 32 else 5 if x >= 16 else 4 if x >= 8 else 3 if x >= 4 else 2 if x >= 2 else 1)

    def _js_encode_link(self, cid: CID, name: str, tsize: int, buffer: bytearray, offset: int) -> int:
        """Encode link JavaScript-style (backwards from offset)"""
        i = offset

        # Tsize field (tag 3, wire type 0 = varint)
        if tsize is not None:
            if tsize < 0:
                raise ValueError('Tsize cannot be negative')
            tsize_bytes = self._js_encode_varint(tsize)
            i -= len(tsize_bytes)
            buffer[i:i+len(tsize_bytes)] = tsize_bytes
            i -= 1
            buffer[i] = 0x18  # field 3, varint

        # Name field (tag 2, wire type 2 = length-delimited) - всегда кодируем, даже пустое имя
        if name is not None:
            name_bytes = name.encode('utf-8')
            i -= len(name_bytes)
            if name_bytes:
                buffer[i:i+len(name_bytes)] = name_bytes
            name_len_bytes = self._js_encode_varint(len(name_bytes))
            i -= len(name_len_bytes)
            buffer[i:i+len(name_len_bytes)] = name_len_bytes
            i -= 1
            buffer[i] = 0x12  # field 2, length-delimited

        # Hash field (tag 1, wire type 2 = length-delimited)
        cid_bytes = bytes(cid)
        i -= len(cid_bytes)
        buffer[i:i+len(cid_bytes)] = cid_bytes
        cid_len_bytes = self._js_encode_varint(len(cid_bytes))
        i -= len(cid_len_bytes)
        buffer[i:i+len(cid_len_bytes)] = cid_len_bytes
        i -= 1
        buffer[i] = 0x0a  # field 1, length-delimited

        return offset - i

    def _js_size_link(self, cid: CID, name: str, tsize: int) -> int:
        """Calculate link size JavaScript-style"""
        n = 0

        if cid:
            cid_len = len(bytes(cid))
            n += 1 + cid_len + self._js_sov(cid_len)

        if name is not None:
            name_len = len(name.encode('utf-8'))
            n += 1 + name_len + self._js_sov(name_len)

        if tsize is not None:
            n += 1 + self._js_sov(tsize)

        return n

    def _js_encode_node(self, data: bytes, links: list[tuple[CID, str, int]]) -> bytes:
        """Encode DAG-PB node JavaScript-style"""
        # Calculate total size
        size = 0

        if data:
            data_len = len(data)
            size += 1 + data_len + self._js_sov(data_len)

        if links:
            for cid, name, tsize in links:
                link_size = self._js_size_link(cid, name, tsize)
                size += 1 + link_size + self._js_sov(link_size)

        # Create buffer
        buffer = bytearray(size)
        i = size

        # Data field (tag 1, wire type 2 = length-delimited)
        if data:
            i -= len(data)
            buffer[i:i+len(data)] = data
            data_len_bytes = self._js_encode_varint(len(data))
            i -= len(data_len_bytes)
            buffer[i:i+len(data_len_bytes)] = data_len_bytes
            i -= 1
            buffer[i] = 0x0a  # field 1, length-delimited

        # Links field (tag 2, wire type 2 = length-delimited) in reverse order
        if links:
            for cid, name, tsize in reversed(links):
                link_size = self._js_encode_link(cid, name, tsize, buffer, i)
                i -= link_size
                link_len_bytes = self._js_encode_varint(link_size)
                i -= len(link_len_bytes)
                buffer[i:i+len(link_len_bytes)] = link_len_bytes
                i -= 1
                buffer[i] = 0x12  # field 2, length-delimited

        return bytes(buffer)

    def _serialize_unixfs_parent_node(self, chunk_cids: list[CID], chunk_block_sizes: list[int], chunk_data_sizes: list[int], total_size: int) -> bytes:
        """Serialize UnixFS parent node that links to child chunks."""
        # Create UnixFS data structure for parent file node
        unixfs = unixfs_pb2.Data()  # type: ignore[attr-defined]
        unixfs.Type = unixfs_pb2.Data.File  # type: ignore[attr-defined]

        # Add original chunk data sizes (not encoded block sizes) to UnixFS metadata
        for size in chunk_data_sizes:
            unixfs.blocksizes.append(size)

        # Calculate filesize as sum of blocksizes (matching JavaScript behavior)
        # In JavaScript: fileSize() { sum = 0n; blockSizes.forEach(size => sum += size); return sum; }
        unixfs.filesize = sum(chunk_data_sizes)

        unixfs_serialized = unixfs.SerializeToString()

        # Create links list for DAG-PB encoding
        links = []
        for cid, block_size in zip(chunk_cids, chunk_block_sizes):
            links.append((cid, "", block_size))  # (CID, Name, Tsize)

        # Encode using JavaScript-compatible DAG-PB encoding
        return self._js_encode_node(unixfs_serialized, links)

    def _create_cid_from_pb_node(self, pb_node_serialized: bytes) -> CID:
        root_digest = multihash.digest(pb_node_serialized, "sha2-256")
        return CID("base58btc", 0, "dag-pb", root_digest)

    def create_unixfs_based_cid(self, data_bytes: bytes) -> str:
        """Create UnixFS-based CID matching ipfs-unixfs-importer behavior.

        For files > 262144 bytes, this chunks the data and creates a tree structure
        matching the JavaScript ipfs-unixfs-importer with rawLeaves: false.
        """
        chunks = self._chunk_data(data_bytes)

        if len(chunks) == 1:
            # Single chunk - create a simple UnixFS file node
            pb_node_serialized = self._serialize_unixfs_leaf_node(data_bytes)
            return self._create_cid_from_pb_node(pb_node_serialized).encode()
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

            # Create parent node that links to all chunks
            parent_node_serialized = self._serialize_unixfs_parent_node(
                chunk_cids, chunk_block_sizes, chunk_data_sizes, len(data_bytes)
            )
            parent_cid = self._create_cid_from_pb_node(parent_node_serialized)

            return parent_cid.encode()

    def create_car_from_data(self, data_bytes: bytes) -> CarFile:
        """Create a complete CAR file using UnixFS structure.

        Uses create_unixfs_based_cid to properly handle chunking and create
        all necessary blocks for files larger than 262144 bytes.
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
                # Add chunk block to CAR
                blocks.append((chunk_cid, leaf_node_serialized))

            # Create parent node that links to all chunks
            parent_node_serialized = self._serialize_unixfs_parent_node(
                chunk_cids, chunk_block_sizes, chunk_data_sizes, len(data_bytes)
            )
            root_cid = self._create_cid_from_pb_node(parent_node_serialized)
            # Add parent block to CAR
            blocks.append((root_cid, parent_node_serialized))

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
