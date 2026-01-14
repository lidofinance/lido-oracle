from abc import ABC

from src.modules.oracles.common.consensus import ConsensusModule
from src.modules.oracles.common.oracle_module import BaseModule


class OracleModule(BaseModule, ConsensusModule, ABC):
    pass
