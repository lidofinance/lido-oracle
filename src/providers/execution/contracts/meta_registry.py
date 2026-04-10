import logging
from dataclasses import dataclass

from web3.types import BlockIdentifier

from src.providers.execution.base_interface import ContractInterface
from src.types import NodeOperatorGlobalIndex, NodeOperatorId, StakingModuleId
from src.utils.abi import named_tuple_to_dataclass
from src.utils.cache import global_lru_cache as lru_cache
from src.utils.dataclass import FromResponse, Nested


logger = logging.getLogger(__name__)


@dataclass
class SubNodeOperator:
    node_operator_id: NodeOperatorId
    share: int


@dataclass
class ExternalOperator:
    data: bytes | bytearray | int | str

    def get_gid(self) -> NodeOperatorGlobalIndex:
        """
        Parse external_operator data attribute (8 bytes):
        - Byte 0: type
        - Byte 1: staking module id
        - Bytes 2-7: node operator id (6 bytes)

        Accepts bytes, bytearray, a big-endian int, or a hex string
        (with or without a leading "0x").
        """
        if isinstance(self.data, int):
            data_bytes: bytes = self.data.to_bytes(8, 'big')
        elif isinstance(self.data, str):
            hex_str = self.data[2:] if self.data.startswith('0x') else self.data
            data_bytes = bytes.fromhex(hex_str)
        else:
            data_bytes = bytes(self.data)

        if len(data_bytes) != 8:
            raise ValueError(f"Expected 8 bytes, got {len(data_bytes)}")

        staking_module_id = StakingModuleId(data_bytes[1])
        node_operator_id = NodeOperatorId(int.from_bytes(data_bytes[2:8], byteorder='big'))

        return staking_module_id, node_operator_id


@dataclass
class OperatorGroup(Nested, FromResponse):
    sub_node_operators: list[SubNodeOperator]
    external_operators: list[ExternalOperator]


class MetaRegistryContract(ContractInterface):
    abi_path = './assets/MetaRegistry.json'

    @lru_cache(maxsize=1)
    def get_operator_groups_count(self, block_identifier: BlockIdentifier) -> int:
        """
        Returns the count of operator groups
        """
        response = self.functions.getOperatorGroupsCount().call(block_identifier=block_identifier)

        logger.info(
            {
                'msg': 'Call `getOperatorGroupsCount()`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    def get_operator_group(self, group_id: int, block_identifier: BlockIdentifier) -> OperatorGroup:
        """
        Returns the operator group information for the given group ID
        """
        response = self.functions.getOperatorGroup(group_id).call(block_identifier=block_identifier)
        response = named_tuple_to_dataclass(response, OperatorGroup)

        logger.info(
            {
                'msg': f'Call `getOperatorGroup({group_id})`.',
                'value': response,
                'block_identifier': repr(block_identifier),
                'to': self.address,
            }
        )
        return response

    def get_all_groups(self, block_identifier: BlockIdentifier) -> list[OperatorGroup]:
        all_groups = self.get_operator_groups_count(block_identifier)
        return [self.get_operator_group(group_id, block_identifier) for group_id in range(all_groups)]
