from src.modules.accounting.types import AccountingProcessingState
from src.modules.ejector.types import EjectorProcessingState
from tests.factory.web3_factory import Web3Factory


class AccountingProcessingStateFactory(Web3Factory):
    __model__ = AccountingProcessingState


class EjectorProcessingStateFactory(Web3Factory):
    __model__ = EjectorProcessingState
