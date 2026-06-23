from ipld_dag_pb import PBLink, PBNode, encode as dag_pb_encode
from multiformats import CID, multihash

from .schemes import unixfs_pb2


DEFAULT_CHUNK_SIZE = 262144  # Default chunk size for IPFS UnixFS (256KB)

Block = tuple[CID, bytes]


class CARConverter:
    """CAR (Content Addressable aRchive) format converter.

    Spec: https://ipld.io/specs/transport/car/carv1/

    """

    def _chunk_data(self, data_bytes: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[bytes]:
        chunks = []
        for i in range(0, len(data_bytes), chunk_size):
            chunks.append(data_bytes[i : i + chunk_size])
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

    def _serialize_unixfs_parent_node(self, leafs_info: list[tuple[CID, int, int]]) -> bytes:
        """Serialize UnixFS parent node that links to child chunks.

        Source: https://github.com/ipfs/js-ipfs-unixfs/blob/master/packages/ipfs-unixfs-importer/src/dag-builder/file.ts#L122-L186
        """
        unixfs = unixfs_pb2.Data()  # type: ignore[attr-defined]
        unixfs.Type = unixfs_pb2.Data.File  # type: ignore[attr-defined]

        links = []
        total_file_size = 0

        for cid, block_size, data_size in leafs_info:
            unixfs.blocksizes.append(data_size)
            total_file_size += data_size
            links.append(PBLink(hash=cid, name="", size=block_size))

        unixfs.filesize = total_file_size
        unixfs_serialized = unixfs.SerializeToString()

        pb_node = PBNode(data=unixfs_serialized, links=links)
        return dag_pb_encode(pb_node)

    def _create_cid_from_pb_node(self, pb_node_serialized: bytes) -> CID:
        root_digest = multihash.digest(pb_node_serialized, "sha2-256")
        return CID("base58btc", 0, "dag-pb", root_digest)

    def _build_unixfs_blocks_and_root(self, data_bytes: bytes) -> tuple[CID, list[Block]]:
        """Build UnixFS blocks and return root CID with all blocks.

        This method handles the common logic for both CID creation and CAR file generation.

        For files > DEFAULT_CHUNK_SIZE bytes, this chunks the data and creates a tree structure
        matching the ipfs-unixfs-importer with rawLeaves: false.

        Returns:
            tuple: (root_cid, blocks) where blocks is a list of (CID, bytes) tuples
        """
        chunks = self._chunk_data(data_bytes)
        blocks = []

        if len(chunks) <= 1:
            # Single chunk - create a simple UnixFS file node
            root_node_serialized = self._serialize_unixfs_leaf_node(data_bytes)
        else:
            # Multiple chunks - create leaf nodes for each chunk and a parent node
            all_chunks_info: list[tuple[CID, int, int]] = []  # (cid, block_size, data_size)

            for chunk in chunks:
                leaf_node_serialized = self._serialize_unixfs_leaf_node(chunk)
                chunk_cid = self._create_cid_from_pb_node(leaf_node_serialized)
                all_chunks_info.append((chunk_cid, len(leaf_node_serialized), len(chunk)))
                blocks.append((chunk_cid, leaf_node_serialized))

            # Create parent node that links to all chunks
            root_node_serialized = self._serialize_unixfs_parent_node(all_chunks_info)

        root_cid = self._create_cid_from_pb_node(root_node_serialized)
        blocks.append((root_cid, root_node_serialized))
        return root_cid, blocks

    def create_unixfs_based_cid(self, data_bytes: bytes) -> str:
        root_cid, _ = self._build_unixfs_blocks_and_root(data_bytes)
        return root_cid.encode()
