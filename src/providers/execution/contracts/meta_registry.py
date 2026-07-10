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
    data: bytes

    def get_gid(self) -> NodeOperatorGlobalIndex:
        """
        Parse external_operator data attribute (10 bytes):
        - Byte 0: OperatorType enum (1 byte)
        - Byte 1: staking module id (uint8, 1 byte)
        - Bytes 2-9: node operator id (uint64, 8 bytes)
        """
        # Ensure we have exactly 10 bytes
        if len(self.data) != 10:
            raise ValueError(f"Expected 10 bytes, got {len(self.data)}")

        # Parse the components
        # type_byte = data_bytes[0]
        staking_module_id = StakingModuleId(self.data[1])

        # Node operator id is 8 bytes (bytes 2-9)
        node_operator_id = NodeOperatorId(int.from_bytes(self.data[2:10], byteorder='big'))

        return staking_module_id, node_operator_id


@dataclass
class OperatorGroup(Nested, FromResponse):
    name: str
    sub_node_operators: list[SubNodeOperator]
    external_operators: list[ExternalOperator]

    def has_connection(self):
        return len(self.sub_node_operators) > 0 and len(self.external_operators) > 0


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
        # Group IDs are one-based: the contract reserves NO_GROUP_ID = 0
        # and creates real groups with IDs 1..groupsCount.
        all_groups = self.get_operator_groups_count(block_identifier)
        return [self.get_operator_group(group_id, block_identifier) for group_id in range(1, all_groups + 1)]
