from modules.oracles.staking_modules.base import SMPerformanceOracle


class CSPerformanceOracle(SMPerformanceOracle):
    """Community Staking Module Performance Oracle"""

    COMPATIBLE_CONTRACT_VERSION = 3
    COMPATIBLE_CONSENSUS_VERSION = 4
