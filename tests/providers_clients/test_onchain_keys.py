from unittest.mock import Mock

import pytest
from eth_abi.abi import decode, encode
from eth_typing import HexStr
from web3 import Web3
from web3.exceptions import Web3RPCError

from src.providers.keys.onchain import (
    AGGREGATE3,
    CSM_GAS_PER_KEY,
    GET_NODE_OPERATOR_SUMMARY,
    GET_NODE_OPERATORS_COUNT,
    GET_SIGNING_KEYS_WITH_SIGNATURES,
    GET_TYPE,
    MULTICALL3_ADDRESS,
    NOR_GAS_PER_KEY,
    NOR_GET_SIGNING_KEYS,
    NOR_MODULE_TYPE,
    PUBKEY_LENGTH,
    SIGNATURE_LENGTH,
    OnchainKeysConfig,
    OnchainKeysError,
    OnchainKeysFetcher,
    Read,
    ReadKind,
)
from src.types import BlockHash, NodeOperatorId


NOR = Web3.to_checksum_address('0x' + '11' * 20)
CSM = Web3.to_checksum_address('0x' + '22' * 20)
BLOCK_HASH = BlockHash(HexStr('0x' + 'ab' * 32))


def pubkey(module: str, operator_id: int, index: int) -> bytes:
    return (bytes.fromhex(module[2:4]) + bytes([operator_id, index % 256, index // 256])).ljust(PUBKEY_LENGTH, b'\x01')


def signature(module: str, operator_id: int, index: int) -> bytes:
    return pubkey(module, operator_id, index).ljust(SIGNATURE_LENGTH, b'\x02')


class FakeChain:
    """Serves the staking module and Multicall3 reads by decoding the calldata."""

    def __init__(self, modules: dict[str, tuple[str, list[int]]], max_keys_per_call: int | None = None):
        # module -> (type, deposited keys per operator)
        self.modules = modules
        self.max_keys_per_call = max_keys_per_call
        self.calls: list[tuple[str, int]] = []  # (target, keys requested)
        self.used_flag = True
        self.truncate_keys = False
        self.same_keys = False

    def eth_call(self, to: str, calldata: bytes, block_hash: BlockHash) -> bytes:
        assert block_hash == BLOCK_HASH
        if to == MULTICALL3_ADDRESS:
            (calls,) = decode(['(address,bool,bytes)[]'], calldata[4:])
            self.calls.append((to, sum(self._keys_requested(data) for _, _, data in calls)))
            self._check_limit(sum(self._keys_requested(data) for _, _, data in calls))
            results = [(True, self._module_call(Web3.to_checksum_address(target), data)) for target, _, data in calls]
            return encode(['(bool,bytes)[]'], [results])
        self.calls.append((to, self._keys_requested(calldata)))
        self._check_limit(self._keys_requested(calldata))
        return self._module_call(to, calldata)

    def _check_limit(self, keys: int) -> None:
        if self.max_keys_per_call is not None and keys > self.max_keys_per_call:
            raise Web3RPCError('out of gas')

    @staticmethod
    def _keys_requested(calldata: bytes) -> int:
        if calldata[:4] in (NOR_GET_SIGNING_KEYS, GET_SIGNING_KEYS_WITH_SIGNATURES):
            return decode(['uint256', 'uint256', 'uint256'], calldata[4:])[2]
        return 0

    def _module_call(self, module: str, calldata: bytes) -> bytes:
        module_type, deposited = self.modules[module]
        selector, args = calldata[:4], calldata[4:]
        if selector == GET_TYPE:
            return encode(['bytes32'], [module_type.encode().ljust(32, b'\0')])
        if selector == GET_NODE_OPERATORS_COUNT:
            return encode(['uint256'], [len(deposited)])
        if selector == GET_NODE_OPERATOR_SUMMARY:
            (operator_id,) = decode(['uint256'], args)
            return encode(['uint256'] * 8, [0, 0, 0, 0, 0, 0, deposited[operator_id], 0])

        operator_id, start, count = decode(['uint256', 'uint256', 'uint256'], args)
        indexes = range(start, start + count - (1 if self.truncate_keys else 0))
        pubkeys = b''.join(pubkey(module, operator_id, 0 if self.same_keys else i) for i in indexes)
        signatures = b''.join(signature(module, operator_id, i) for i in indexes)
        if selector == NOR_GET_SIGNING_KEYS:
            return encode(['bytes', 'bytes', 'bool[]'], [pubkeys, signatures, [self.used_flag] * len(indexes)])
        if selector == GET_SIGNING_KEYS_WITH_SIGNATURES:
            return encode(['bytes', 'bytes'], [pubkeys, signatures])
        raise ValueError('execution reverted')


@pytest.mark.unit
class TestOnchainKeysFetcher:
    @pytest.fixture
    def chain(self) -> FakeChain:
        return FakeChain(
            {
                NOR: (NOR_MODULE_TYPE, [7, 0, 3]),
                CSM: ('community-onchain-v1', [2, 5]),
            }
        )

    def make_fetcher(self, chain: FakeChain, multicall_deployed: bool = True, **config) -> OnchainKeysFetcher:
        w3 = Mock()
        w3.eth.call.side_effect = lambda tx, block_identifier: chain.eth_call(
            tx['to'], bytes.fromhex(tx['data'][2:]), block_identifier
        )
        w3.eth.get_code.return_value = b'\x60' if multicall_deployed else b''
        return OnchainKeysFetcher(w3, OnchainKeysConfig(**{'workers': 4, **config}))

    @staticmethod
    def expected_keys(chain: FakeChain, module: str) -> list[tuple[int, int, str, str]]:
        _, deposited = chain.modules[module]
        return [
            (
                operator_id,
                i,
                '0x' + pubkey(module, operator_id, i).hex(),
                '0x' + signature(module, operator_id, i).hex(),
            )
            for operator_id, count in enumerate(deposited)
            for i in range(count)
        ]

    @staticmethod
    def actual_keys(module_keys) -> list[tuple[int, int, str, str]]:
        return [(k.operator_index, k.index, k.key, k.deposit_signature) for k in module_keys.keys]

    @pytest.mark.parametrize('use_multicall', [True, False])
    def test_fetch_modules_keys__nor_and_csm_modules__returns_deposited_keys_sorted(self, chain, use_multicall):
        # Arrange: small limits so the keys are read in many chunks
        fetcher = self.make_fetcher(
            chain, use_multicall=use_multicall, call_gas_limit=4 * NOR_GAS_PER_KEY, call_return_bytes_limit=10_000
        )

        # Act
        nor, csm = fetcher.fetch_modules_keys([NOR, CSM], BLOCK_HASH)

        # Assert
        assert self.actual_keys(nor) == self.expected_keys(chain, NOR)
        assert self.actual_keys(csm) == self.expected_keys(chain, CSM)
        assert nor.deposited_keys == {0: 7, 1: 0, 2: 3}
        assert csm.deposited_keys == {0: 2, 1: 5}
        assert all(k.used and k.module_address == NOR for k in nor.keys)
        assert all(k.used and k.module_address == CSM for k in csm.keys)

    def test_fetch_modules_keys__multicall_enabled__packs_reads_into_aggregate3(self, chain):
        fetcher = self.make_fetcher(chain, use_multicall=True)

        fetcher.fetch_modules_keys([NOR, CSM], BLOCK_HASH)

        # getType and getNodeOperatorsCount per module, then one aggregate3 for summaries and one for keys
        assert [target for target, _ in chain.calls].count(MULTICALL3_ADDRESS) == 2
        assert len(chain.calls) == 2 * 2 + 2

    def test_fetch_modules_keys__multicall_not_deployed__reads_without_multicall(self, chain):
        fetcher = self.make_fetcher(chain, multicall_deployed=False, use_multicall=True)

        nor, csm = fetcher.fetch_modules_keys([NOR, CSM], BLOCK_HASH)

        assert MULTICALL3_ADDRESS not in [target for target, _ in chain.calls]
        assert self.actual_keys(nor) == self.expected_keys(chain, NOR)
        assert self.actual_keys(csm) == self.expected_keys(chain, CSM)

    @pytest.mark.parametrize('use_multicall', [True, False])
    def test_fetch_modules_keys__node_rejects_heavy_calls__splits_and_returns_all_keys(self, chain, use_multicall):
        # Arrange: the node accepts less than the configured budget
        chain.max_keys_per_call = 2
        fetcher = self.make_fetcher(chain, use_multicall=use_multicall)

        # Act
        nor, csm = fetcher.fetch_modules_keys([NOR, CSM], BLOCK_HASH)

        # Assert
        assert self.actual_keys(nor) == self.expected_keys(chain, NOR)
        assert self.actual_keys(csm) == self.expected_keys(chain, CSM)

    def test_fetch_modules_keys__single_key_read_fails__raises(self, chain):
        chain.max_keys_per_call = 0
        fetcher = self.make_fetcher(chain)

        with pytest.raises(Web3RPCError, match='out of gas'):
            fetcher.fetch_modules_keys([NOR], BLOCK_HASH)

    def test_fetch_modules_keys__transport_error__raises_without_splitting(self, chain):
        # Arrange
        fetcher = self.make_fetcher(chain)
        fetcher.w3.eth.call.side_effect = ConnectionError('429 Too Many Requests')

        # Act
        with pytest.raises(ConnectionError):
            fetcher.fetch_modules_keys([NOR], BLOCK_HASH)

        # Assert: getType only, no retries in halves
        assert fetcher.w3.eth.call.call_count == 1

    def test_fetch_modules_keys__nor_key_not_used__raises(self, chain):
        chain.used_flag = False
        fetcher = self.make_fetcher(chain)

        with pytest.raises(OnchainKeysError, match='used flags'):
            fetcher.fetch_modules_keys([NOR], BLOCK_HASH)

    def test_fetch_modules_keys__fewer_keys_returned__raises(self, chain):
        chain.truncate_keys = True
        fetcher = self.make_fetcher(chain)

        with pytest.raises(OnchainKeysError, match='keys data length'):
            fetcher.fetch_modules_keys([CSM], BLOCK_HASH)

    def test_fetch_modules_keys__duplicated_key__raises(self, chain):
        chain.same_keys = True
        fetcher = self.make_fetcher(chain)

        with pytest.raises(OnchainKeysError, match='Duplicated key'):
            fetcher.fetch_modules_keys([CSM], BLOCK_HASH)

    def test_keys_reads__many_keys__chunks_within_gas_and_return_data_limits(self, chain):
        fetcher = self.make_fetcher(chain, call_gas_limit=10 * CSM_GAS_PER_KEY, call_return_bytes_limit=1_000_000)

        reads = fetcher._keys_reads(ReadKind.CSM_KEYS, CSM, 3, 25)

        assert [(r.start, r.count) for r in reads] == [(0, 10), (10, 10), (20, 5)]
        assert all(r.operator_id == 3 for r in reads)

    def test_keys_reads__return_data_limit_lower__chunks_by_return_data(self, chain):
        fetcher = self.make_fetcher(chain, call_gas_limit=10**9, call_return_bytes_limit=256 + 3 * 176)

        reads = fetcher._keys_reads(ReadKind.NOR_KEYS, NOR, 0, 7)

        assert [r.count for r in reads] == [3, 3, 1]

    def test_keys_reads__no_keys__no_reads(self, chain):
        assert self.make_fetcher(chain)._keys_reads(ReadKind.NOR_KEYS, NOR, 0, 0) == []

    def test_pack__reads_over_budget__starts_new_group(self, chain):
        fetcher = self.make_fetcher(chain, call_gas_limit=3 * NOR_GAS_PER_KEY, call_return_bytes_limit=10**6)
        reads = [Read(ReadKind.NOR_KEYS, NOR, 0, 0, 2), Read(ReadKind.NOR_KEYS, NOR, 0, 2, 1)]
        reads += [Read(ReadKind.NOR_KEYS, NOR, 1, 0, 3)]

        groups = fetcher._pack(reads, use_multicall=True)

        assert groups == [reads[:2], reads[2:]]

    def test_pack__multicall_disabled__one_read_per_call(self, chain):
        fetcher = self.make_fetcher(chain)
        reads = [Read(ReadKind.SUMMARY, NOR, 0), Read(ReadKind.SUMMARY, NOR, 1)]

        assert fetcher._pack(reads, use_multicall=False) == [[reads[0]], [reads[1]]]

    def test_read_split__keys_read__halves_range(self):
        first, second = Read(ReadKind.CSM_KEYS, CSM, 1, 10, 5).split()

        assert (first.start, first.count, second.start, second.count) == (10, 2, 12, 3)

    @pytest.mark.parametrize(
        'read', [Read(ReadKind.SUMMARY, CSM, 1), Read(ReadKind.CSM_KEYS, CSM, 1, 10, 1)], ids=['summary', 'single_key']
    )
    def test_read_split__not_splittable__returns_none(self, read):
        assert read.split() is None

    def test_read_calldata__summary__encodes_operator_id(self):
        assert Read(ReadKind.SUMMARY, CSM, 5).calldata == GET_NODE_OPERATOR_SUMMARY + encode(['uint256'], [5])

    def test_fetch_modules_keys__aggregate3_selector__matches_multicall3(self):
        assert AGGREGATE3.hex() == '82ad56cb'

    def test_fetch_modules_keys__no_modules__returns_empty(self, chain):
        assert self.make_fetcher(chain).fetch_modules_keys([], BLOCK_HASH) == []

    def test_fetch_modules_keys__operator_ids__are_node_operator_ids(self, chain):
        (csm,) = self.make_fetcher(chain).fetch_modules_keys([CSM], BLOCK_HASH)

        assert list(csm.deposited_keys) == [NodeOperatorId(0), NodeOperatorId(1)]
