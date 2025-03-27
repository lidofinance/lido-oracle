from src.modules.accounting.types import AccountingProcessingState
from src.modules.ejector.types import EjectorProcessingState
from tests.factory.web3_factory import Web3DataclassFactory


class AccountingProcessingStateFactory(Web3DataclassFactory[AccountingProcessingState]):  # noqa: E701
    ...


class EjectorProcessingStateFactory(Web3DataclassFactory[EjectorProcessingState]):  # noqa: E701
    ...
