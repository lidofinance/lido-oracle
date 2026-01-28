from abc import ABC
from typing import TypeVar

from src.modules.oracles.common.consensus import ConsensusModule
from src.modules.oracles.common.oracle_module import BaseModule
from src.web3py.types import Web3Base


W3 = TypeVar("W3", bound=Web3Base)


class OracleModule(BaseModule[W3], ConsensusModule[W3], ABC):
    pass
