from faker import Faker

from src.providers.execution.contracts.meta_registry import ExternalOperator, OperatorGroup, SubNodeOperator
from tests.factory.web3_factory import Web3DataclassFactory


faker = Faker()


class SubNodeOperatorFactory(Web3DataclassFactory[SubNodeOperator]): ...


class ExternalOperatorFactory(Web3DataclassFactory[ExternalOperator]): ...


class OperatorGroupFactory(Web3DataclassFactory[OperatorGroup]):
    name = faker.name
    sub_node_operators: list = []
    external_operators: list = []
