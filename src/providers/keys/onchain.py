"""Used Lido keys read straight from the staking module contracts, without Keys API.

A key is used (deposited) when its index is below the operator's `totalDepositedValidators`: modules never
delete or reorder deposited keys. So the keys of a module are two reads per operator: the summary, then
`[0, totalDepositedValidators)` of its signing keys.

Mainnet holds ~0.5M deposited keys, ~75 MB of keys and signatures, so the reads are:
- chunked to stay within the node's `eth_call` gas cap and return data limit (both differ between clients),
- packed into Multicall3 `aggregate3` calls to cut round trips,
- sent in parallel.

A call the node rejects (out of gas, revert) is retried split in halves: if a node runs with a lower gas cap
or return data limit than the chunking assumes, the fetch gets slower, not broken.
"""

import logging
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

from eth_abi.abi import decode, encode
from eth_typing import ChecksumAddress, HexStr
from eth_utils.abi import function_signature_to_4byte_selector
from web3 import Web3
from web3.exceptions import ContractLogicError, Web3RPCError

from src.providers.keys.types import LidoKey
from src.types import BlockHash, NodeOperatorId


logger = logging.getLogger(__name__)

PUBKEY_LENGTH = 48
SIGNATURE_LENGTH = 96

# Canonical deterministic deployment, present on mainnet and testnets: https://www.multicall3.com/deployments
MULTICALL3_ADDRESS = Web3.to_checksum_address('0xcA11bde05977b3631167028862bE2a173976CA11')

# `getType()` of NodeOperatorsRegistry (Curated v1 and SDVT). Its `getSigningKeys` returns keys, signatures and
# `used` flags; CSM-like modules (CSM, Curated v2) return keys only from it and need `getSigningKeysWithSignatures`.
NOR_MODULE_TYPE = 'curated-onchain-v1'

# Gas and return data per read, measured on mainnet and rounded up. They only size the chunks: a wrong guess
# costs a split and a retry, not a wrong result.
NOR_GAS_PER_KEY = 25_000
CSM_GAS_PER_KEY = 12_500
SUMMARY_GAS = 120_000
NOR_BYTES_PER_KEY = PUBKEY_LENGTH + SIGNATURE_LENGTH + 32
CSM_BYTES_PER_KEY = PUBKEY_LENGTH + SIGNATURE_LENGTH
SUMMARY_BYTES = 8 * 32
# ABI head and Multicall3 result wrapping of one read.
READ_OVERHEAD_BYTES = 256

# A failed call is halved at most this many times before the error is raised.
MAX_SPLIT_DEPTH = 10


class OnchainKeysError(Exception):
    pass


GET_TYPE = function_signature_to_4byte_selector('getType()')
GET_NODE_OPERATORS_COUNT = function_signature_to_4byte_selector('getNodeOperatorsCount()')
GET_NODE_OPERATOR_SUMMARY = function_signature_to_4byte_selector('getNodeOperatorSummary(uint256)')
NOR_GET_SIGNING_KEYS = function_signature_to_4byte_selector('getSigningKeys(uint256,uint256,uint256)')
GET_SIGNING_KEYS_WITH_SIGNATURES = function_signature_to_4byte_selector(
    'getSigningKeysWithSignatures(uint256,uint256,uint256)'
)
AGGREGATE3 = function_signature_to_4byte_selector('aggregate3((address,bool,bytes)[])')


class ReadKind(Enum):
    SUMMARY = 'summary'
    NOR_KEYS = 'nor_keys'
    CSM_KEYS = 'csm_keys'


@dataclass(frozen=True)
class Read:
    """One contract read. A keys read can be split in halves when the node rejects it as too heavy."""

    kind: ReadKind
    module: ChecksumAddress
    operator_id: int
    start: int = 0
    count: int = 0

    @property
    def calldata(self) -> bytes:
        if self.kind is ReadKind.SUMMARY:
            return GET_NODE_OPERATOR_SUMMARY + encode(['uint256'], [self.operator_id])
        selector = NOR_GET_SIGNING_KEYS if self.kind is ReadKind.NOR_KEYS else GET_SIGNING_KEYS_WITH_SIGNATURES
        return selector + encode(['uint256', 'uint256', 'uint256'], [self.operator_id, self.start, self.count])

    @property
    def gas(self) -> int:
        if self.kind is ReadKind.SUMMARY:
            return SUMMARY_GAS
        return self.count * (NOR_GAS_PER_KEY if self.kind is ReadKind.NOR_KEYS else CSM_GAS_PER_KEY)

    @property
    def return_bytes(self) -> int:
        if self.kind is ReadKind.SUMMARY:
            return SUMMARY_BYTES + READ_OVERHEAD_BYTES
        per_key = NOR_BYTES_PER_KEY if self.kind is ReadKind.NOR_KEYS else CSM_BYTES_PER_KEY
        return self.count * per_key + READ_OVERHEAD_BYTES

    def split(self) -> tuple[Read, Read] | None:
        if self.kind is ReadKind.SUMMARY or self.count < 2:
            return None
        half = self.count // 2
        return (
            Read(self.kind, self.module, self.operator_id, self.start, half),
            Read(self.kind, self.module, self.operator_id, self.start + half, self.count - half),
        )


@dataclass(frozen=True)
class OnchainKeysConfig:
    # Parallel eth_call requests.
    workers: int = 16
    # Pack reads into Multicall3 `aggregate3`. Without it every read is its own eth_call.
    use_multicall: bool = True
    # Per eth_call. Default `eth_call` gas cap is 50M in Geth, Erigon and Reth, 100M in Nethermind.
    call_gas_limit: int = 25_000_000
    # Per eth_call. Small responses cost nothing in speed with parallel requests (measured on mainnet) and stay
    # clear of response size limits of nodes and proxies in front of them.
    call_return_bytes_limit: int = 100_000
    multicall_address: ChecksumAddress = MULTICALL3_ADDRESS


@dataclass(frozen=True)
class ModuleKeys:
    module_address: ChecksumAddress
    # Every operator of the module, including the ones without deposited keys -> number of deposited keys.
    deposited_keys: dict[NodeOperatorId, int]
    # Sorted by operator id, then key index.
    keys: list[LidoKey]


class OnchainKeysFetcher:
    def __init__(self, w3: Web3, config: OnchainKeysConfig):
        self.w3 = w3
        self.config = config

    def fetch_modules_keys(self, modules: Sequence[ChecksumAddress], block_hash: BlockHash) -> list[ModuleKeys]:
        """Used keys of each module, in the given order, read at `block_hash`."""
        started = time.monotonic()
        use_multicall = self.config.use_multicall and self._is_multicall_deployed(block_hash)

        kinds: dict[ChecksumAddress, ReadKind] = {}
        summaries: list[Read] = []
        for module in modules:
            module_type = decode(['bytes32'], self._eth_call(module, GET_TYPE, block_hash))[0]
            is_nor = module_type.rstrip(b'\0').decode() == NOR_MODULE_TYPE
            kinds[module] = ReadKind.NOR_KEYS if is_nor else ReadKind.CSM_KEYS
            count = decode(['uint256'], self._eth_call(module, GET_NODE_OPERATORS_COUNT, block_hash))[0]
            summaries.extend(Read(ReadKind.SUMMARY, module, operator_id) for operator_id in range(count))

        deposited: dict[ChecksumAddress, dict[NodeOperatorId, int]] = {module: {} for module in modules}
        for read, data in self._execute(summaries, block_hash, use_multicall):
            # NodeOperatorSummary: (..., totalExitedValidators, totalDepositedValidators, depositableValidatorsCount)
            deposited[read.module][NodeOperatorId(read.operator_id)] = decode(['uint256'] * 8, data)[6]

        key_reads = [
            read
            for module in modules
            for operator_id, count in sorted(deposited[module].items())
            for read in self._keys_reads(kinds[module], module, operator_id, count)
        ]

        keys: dict[ChecksumAddress, list[LidoKey]] = {module: [] for module in modules}
        for read, data in self._execute(key_reads, block_hash, use_multicall):
            keys[read.module].extend(self._decode_keys(read, data))

        result = []
        for module in modules:
            module_keys = sorted(keys[module], key=lambda k: (k.operator_index, k.index))
            self._check_keys(module, deposited[module], module_keys)
            result.append(ModuleKeys(module, deposited[module], module_keys))

        logger.info(
            {
                'msg': 'Fetched used keys from staking modules.',
                'modules': len(modules),
                'operators': len(summaries),
                'keys': sum(len(m.keys) for m in result),
                'duration_seconds': round(time.monotonic() - started, 2),
                'multicall': use_multicall,
                'workers': self.config.workers,
            }
        )
        return result

    def _keys_reads(self, kind: ReadKind, module: ChecksumAddress, operator_id: int, count: int) -> list[Read]:
        """Splits an operator's deposited keys into reads that each fit one eth_call on its own."""
        sample = Read(kind, module, operator_id, 0, 1)
        max_keys = max(
            1,
            min(
                self.config.call_gas_limit // sample.gas,
                (self.config.call_return_bytes_limit - READ_OVERHEAD_BYTES)
                // (sample.return_bytes - READ_OVERHEAD_BYTES),
            ),
        )
        return [
            Read(kind, module, operator_id, start, min(max_keys, count - start)) for start in range(0, count, max_keys)
        ]

    def _pack(self, reads: Sequence[Read], use_multicall: bool) -> list[list[Read]]:
        """Groups reads into eth_calls within the gas and return data limits."""
        if not use_multicall:
            return [[read] for read in reads]

        groups: list[list[Read]] = []
        group: list[Read] = []
        gas = size = 0
        for read in reads:
            if group and (
                gas + read.gas > self.config.call_gas_limit
                or size + read.return_bytes > self.config.call_return_bytes_limit
            ):
                groups.append(group)
                group, gas, size = [], 0, 0
            group.append(read)
            gas += read.gas
            size += read.return_bytes
        if group:
            groups.append(group)
        return groups

    def _execute(self, reads: Sequence[Read], block_hash: BlockHash, use_multicall: bool) -> list[tuple[Read, bytes]]:
        groups = self._pack(reads, use_multicall)
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            results = pool.map(lambda group: self._execute_group(group, block_hash, use_multicall, 0), groups)
            return [pair for group_result in results for pair in group_result]

    def _execute_group(
        self, group: list[Read], block_hash: BlockHash, use_multicall: bool, depth: int
    ) -> list[tuple[Read, bytes]]:
        try:
            if len(group) == 1:
                return [(group[0], self._eth_call(group[0].module, group[0].calldata, block_hash))]
            return list(zip(group, self._multicall(group, block_hash), strict=True))
        # The node rejected the call itself (out of gas, revert, too much data). Transport errors are not retried
        # here: halving would only multiply requests to a node that is down or rate limiting.
        except (ContractLogicError, Web3RPCError) as error:
            parts: Sequence[list[Read]]
            if len(group) > 1:
                parts = [group[: len(group) // 2], group[len(group) // 2 :]]
            elif (halves := group[0].split()) is not None:
                parts = [[halves[0]], [halves[1]]]
            else:
                raise

            if depth >= MAX_SPLIT_DEPTH:
                raise

            logger.warning(
                {
                    'msg': 'eth_call with keys failed, retrying in halves.',
                    'reads': len(group),
                    'gas': sum(r.gas for r in group),
                    'return_bytes': sum(r.return_bytes for r in group),
                    'depth': depth,
                    'error': repr(error)[:300],
                }
            )
            return [pair for part in parts for pair in self._execute_group(part, block_hash, use_multicall, depth + 1)]

    def _multicall(self, group: list[Read], block_hash: BlockHash) -> list[bytes]:
        calldata = AGGREGATE3 + encode(
            ['(address,bool,bytes)[]'], [[(read.module, False, read.calldata) for read in group]]
        )
        response = self._eth_call(self.config.multicall_address, calldata, block_hash)
        results = decode(['(bool,bytes)[]'], response)[0]
        return [data for _, data in results]

    def _eth_call(self, to: ChecksumAddress, calldata: bytes, block_hash: BlockHash) -> bytes:
        return bytes(self.w3.eth.call({'to': to, 'data': HexStr('0x' + calldata.hex())}, block_identifier=block_hash))

    def _is_multicall_deployed(self, block_hash: BlockHash) -> bool:
        deployed = self.w3.eth.get_code(self.config.multicall_address, block_identifier=block_hash) != b''
        if not deployed:
            logger.warning(
                {
                    'msg': 'Multicall3 is not deployed, reading keys without it.',
                    'address': self.config.multicall_address,
                }
            )
        return deployed

    @staticmethod
    def _decode_keys(read: Read, data: bytes) -> list[LidoKey]:
        if read.kind is ReadKind.NOR_KEYS:
            pubkeys, signatures, used = decode(['bytes', 'bytes', 'bool[]'], data)
            if not all(used) or len(used) != read.count:
                raise OnchainKeysError(f'Unexpected used flags for deposited keys: {read=}')
        else:
            pubkeys, signatures = decode(['bytes', 'bytes'], data)

        if len(pubkeys) != read.count * PUBKEY_LENGTH or len(signatures) != read.count * SIGNATURE_LENGTH:
            raise OnchainKeysError(f'Unexpected keys data length: {read=}, {len(pubkeys)=}, {len(signatures)=}')

        return [
            LidoKey(
                index=read.start + i,
                key=HexStr('0x' + pubkeys[i * PUBKEY_LENGTH : (i + 1) * PUBKEY_LENGTH].hex()),
                deposit_signature=HexStr('0x' + signatures[i * SIGNATURE_LENGTH : (i + 1) * SIGNATURE_LENGTH].hex()),
                operator_index=NodeOperatorId(read.operator_id),
                used=True,
                module_address=read.module,
            )
            for i in range(read.count)
        ]

    @staticmethod
    def _check_keys(module: ChecksumAddress, deposited: dict[NodeOperatorId, int], keys: list[LidoKey]) -> None:
        if len(keys) != sum(deposited.values()):
            raise OnchainKeysError(f'Got {len(keys)} keys of {module}, expected {sum(deposited.values())}')
        seen: set[str] = set()
        for key in keys:
            if key.key in seen:
                raise OnchainKeysError(f'Duplicated key in {module}: {key}')
            seen.add(key.key)
