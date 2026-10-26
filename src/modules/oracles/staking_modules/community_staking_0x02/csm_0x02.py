from src.modules.oracles.staking_modules.base import SMPerformanceOracle


class CSM0x02PerformanceOracle(SMPerformanceOracle):
    """Community Staking Module 0x02 Performance Oracle"""

    COMPATIBLE_CONTRACT_VERSION = 3
    COMPATIBLE_CONSENSUS_VERSION = 4
