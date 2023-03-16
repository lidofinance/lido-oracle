import os
import logging

from prometheus_client.metrics import Gauge, Histogram

from pool_metrics import PoolMetrics

logger = logging.getLogger()


class MetricsExporterState:
    _instance = None

    def __new__(cls, *args, **kwargs):
        assert cls._instance is None, 'MetricsExporterState should be instanced only once'
        cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        prometheus_prefix = os.getenv('PROMETHEUS_PREFIX', '')

        self.prevEthV1BlockNumber = Gauge(f'{prometheus_prefix}prevEthV1BlockNumber', 'prevEthV1BlockNumber')  # fixme
        self.currentEthV1BlockNumber = Gauge(
            f'{prometheus_prefix}currentEthV1BlockNumber', 'currentEthV1BlockNumber'
        )  # fixme
        self.nowEthV1BlockNumber = Gauge(f'{prometheus_prefix}nowEthV1BlockNumber', 'nowEthV1BlockNumber')  # fixme

        self.daemonCountDown = Gauge(f'{prometheus_prefix}daemonCountDown', 'daemonCountDown')
        self.deltaSeconds = Gauge(f'{prometheus_prefix}deltaSeconds', 'deltaSeconds')
        self.finalizedEpoch = Gauge(f'{prometheus_prefix}finalizedEpoch', 'finalizedEpoch')
        self.appearedValidators = Gauge(f'{prometheus_prefix}appearedValidators', 'appearedValidators')
        self.reportableFrame = Gauge(f'{prometheus_prefix}reportableFrame', 'reportableFrame')

        self.currentEpoch = Gauge(f'{prometheus_prefix}currentEpoch', 'Current epoch')
        self.currentBeaconBalance = Gauge(f'{prometheus_prefix}currentBeaconBalance', 'currentBeaconBalance')
        self.currentWithdrawalVaultBalance = Gauge(f'{prometheus_prefix}currentWithdrawalVaultBalance', 'currentWithdrawalVaultBalance')
        self.currentBeaconValidators = Gauge(f'{prometheus_prefix}currentBeaconValidators', 'currentBeaconValidators')
        self.currentTimestamp = Gauge(f'{prometheus_prefix}currentTimestamp', 'currentTimestamp')
        self.currentBufferedBalance = Gauge(f'{prometheus_prefix}currentBufferedBalance', 'currentBufferedBalance')
        self.currentDepositedValidators = Gauge(
            f'{prometheus_prefix}currentDepositedValidators', 'currentDepositedValidators'
        )
        self.currentActiveValidatorBalance = Gauge(
            f'{prometheus_prefix}currentActiveValidatorBalance', 'currentActiveValidatorBalance'
        )
        self.currentTotalPooledEther = Gauge(f'{prometheus_prefix}currentTotalPooledEther', 'currentTotalPooledEther')
        self.currentTransientValidators = Gauge(
            f'{prometheus_prefix}currentTransientValidators', 'currentTransientValidators'
        )
        self.currentTransientBalance = Gauge(f'{prometheus_prefix}currentTransientBalance', 'currentTransientBalance')
        self.currentValidatorsKeysNumber = Gauge(f'{prometheus_prefix}validatorsKeysNumber', 'validatorsKeysNumber')

        self.prevEpoch = Gauge(f'{prometheus_prefix}prevEpoch', 'prevEpoch')
        self.prevBeaconBalance = Gauge(f'{prometheus_prefix}prevBeaconBalance', 'prevBeaconBalance')
        self.prevBeaconValidators = Gauge(f'{prometheus_prefix}prevBeaconValidators', 'prevBeaconValidators')
        self.prevTimestamp = Gauge(f'{prometheus_prefix}prevTimestamp', 'prevTimestamp')
        self.prevBufferedBalance = Gauge(f'{prometheus_prefix}prevBufferedBalance', 'prevBufferedBalance')
        self.prevDepositedValidators = Gauge(f'{prometheus_prefix}prevDepositedValidators', 'prevDepositedValidators')
        self.prevActiveValidatorBalance = Gauge(
            f'{prometheus_prefix}prevActiveValidatorBalance', 'prevActiveValidatorBalance'
        )
        self.prevTotalPooledEther = Gauge(f'{prometheus_prefix}prevTotalPooledEther', 'prevTotalPooledEther')
        self.prevTransientValidators = Gauge(f'{prometheus_prefix}prevTransientValidators', 'prevTransientValidators')
        self.prevTransientBalance = Gauge(f'{prometheus_prefix}prevTransientBalance', 'prevTransientBalance')

        # self.totalSupply = Gauge(f'{prometheus_prefix}totalSupply', 'totalSupply')  # fixme
        self.txSuccess = Histogram(f'{prometheus_prefix}txSuccess', 'Successful transactions')
        self.txRevert = Histogram(f'{prometheus_prefix}txRevert', 'Reverted transactions')
        # self.resourceUTime = Gauge(f'{prometheus_prefix}resourceUTime', 'resourceUTime')
        # self.resourceSTime = Gauge(f'{prometheus_prefix}resourceSTime', 'resourceSTime')
        # self.resourceMaxResidentSetSize = Gauge(f'{prometheus_prefix}resourceMaxResidentSetSize', 'resourceMaxResidentSetSize')
        # self.resourceSharedMemorySize = Gauge(f'{prometheus_prefix}resourceSharedMemorySize', 'resourceSharedMemorySize')
        # self.resourceUnsharedMemorySize = Gauge(f'{prometheus_prefix}resourceUnsharedMemorySize', 'resourceUnsharedMemorySize')

        self.stethOraclePrice = Gauge(f'{prometheus_prefix}stethOraclePrice', 'stethOraclePrice')
        self.stethPoolPrice = Gauge(f'{prometheus_prefix}stethPoolPrice', 'stethPoolPrice')

        self.beaconNodeTimeoutCount = Gauge(f'{prometheus_prefix}beaconNodeTimeoutCount', 'beaconNodeTimeoutCount')
        self.timeExhaustedExceptionsCount = Gauge(
            f'{prometheus_prefix}timeExhaustedExceptionsCount', 'timeExhaustedExceptionsCount'
        )
        self.underpricedExceptionsCount = Gauge(
            f'{prometheus_prefix}underpricedExceptionsCount', 'underpricedExceptionsCount'
        )
        self.exceptionsCount = Gauge(f'{prometheus_prefix}exceptionsCount', 'exceptionsCount')

    def set_current_pool_metrics(self, metrics: PoolMetrics):
        self.currentEthV1BlockNumber.set(metrics.blockNumber)
        self.currentEpoch.set(metrics.epoch)
        self.currentBeaconBalance.set(metrics.beaconBalance)
        self.currentWithdrawalVaultBalance.set(metrics.withdrawalVaultBalance)
        self.currentBeaconValidators.set(metrics.beaconValidators)
        self.currentTimestamp.set(metrics.timestamp)
        self.currentBufferedBalance.set(metrics.bufferedBalance)
        self.currentDepositedValidators.set(metrics.depositedValidators)
        self.currentActiveValidatorBalance.set(metrics.activeValidatorBalance)
        self.currentTotalPooledEther.set(metrics.getTotalPooledEther())
        self.currentTransientValidators.set(metrics.getTransientValidators())
        self.currentTransientBalance.set(metrics.getTransientBalance())

        if metrics.validatorsKeysNumber is not None:
            self.currentValidatorsKeysNumber.set(metrics.validatorsKeysNumber)

    def set_prev_pool_metrics(self, metrics: PoolMetrics):
        self.prevEthV1BlockNumber.set(metrics.blockNumber)
        self.prevEpoch.set(metrics.epoch)
        self.prevBeaconBalance.set(metrics.beaconBalance)
        self.prevBeaconValidators.set(metrics.beaconValidators)
        self.prevTimestamp.set(metrics.timestamp)
        self.prevBufferedBalance.set(metrics.bufferedBalance)
        self.prevDepositedValidators.set(metrics.depositedValidators)
        self.prevActiveValidatorBalance.set(metrics.activeValidatorBalance)
        self.prevTotalPooledEther.set(metrics.getTotalPooledEther())
        self.prevTransientValidators.set(metrics.getTransientValidators())
        self.prevTransientBalance.set(metrics.getTransientBalance())

    def set_steth_pool_metrics(self, oraclePrice, poolPrice):
        self.stethOraclePrice.set(oraclePrice)
        self.stethPoolPrice.set(poolPrice)


metrics_exporter_state = MetricsExporterState()


# @metrics_exporter_state.resourceUTime.time()
# def getResourceUTime():
#     return resource.getrusage(resource.RUSAGE_SELF).ru_utime
#
#
# @metrics_exporter_state.resourceSTime.time()
# def getResourceSTime():
#     return resource.getrusage(resource.RUSAGE_SELF).ru_stime
#
#
# @metrics_exporter_state.resourceMaxResidentSetSize.time()
# def getResourceMaxResidentSetSize():
#     return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
#
#
# @metrics_exporter_state.resourceSharedMemorySize.time()
# def getResourceSharedMemorySize():
#     return resource.getrusage(resource.RUSAGE_SELF).ru_ixrss
#
#
# @metrics_exporter_state.resourceUnsharedMemorySize.time()
# def getResourceUnsharedMemorySize():
#     return resource.getrusage(resource.RUSAGE_SELF).ru_idrss
