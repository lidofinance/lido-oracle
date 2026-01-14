from src.modules.oracles.staking_modules.base import SMPerformanceOracle


class CMPerformanceOracle(SMPerformanceOracle):
    """Curated Module Performance Oracle"""

    COMPATIBLE_CONTRACT_VERSION = 1
    COMPATIBLE_CONSENSUS_VERSION = 1
