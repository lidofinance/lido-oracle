import os
import logging

from prometheus_client import start_http_server, Gauge, Summary

from pool_metrics import PoolMetrics

logger = logging.getLogger()


class MetricsExporterState:
    _instance = None

    def __new__(cls, *args, **kwargs):
        assert cls._instance is None, 'MetricsExporterState should be instanced only once'
        cls._instance = super().__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        self.ethV1Blocknumber = Gauge('ethV1Blocknumber', 'ethV1Blocknumber')
        self.daemonCountDown = Gauge('daemonCountDown', 'daemonCountDown')
        self.deltaSeconds = Gauge('deltaSeconds', 'deltaSeconds')
        self.appearedValidators = Gauge('appearedValidators', 'appearedValidators')
        self.reportableFrame = Gauge('reportableFrame', 'reportableFrame')
        self.validatorsKeysNumber = Gauge('validatorsKeysNumber', 'validatorsKeysNumber')

        self.currentEpoch = Gauge('currentEpoch', 'Current epoch')
        self.currentBeaconBalance = Gauge('currentBeaconBalance', 'currentBeaconBalance')
        self.currentBeaconValidators = Gauge('currentBeaconValidators', 'currentBeaconValidators')
        self.currentTimestamp = Gauge('currentTimestamp', 'currentTimestamp')
        self.currentBufferedBalance = Gauge('currentBufferedBalance', 'currentBufferedBalance')
        self.currentDepositedValidators = Gauge('currentDepositedValidators', 'currentDepositedValidators')
        self.currentActiveValidatorBalance = Gauge('currentActiveValidatorBalance', 'currentActiveValidatorBalance')
        self.currentTotalPooledEther = Gauge('currentTotalPooledEther', 'currentTotalPooledEther')
        self.currentTransientValidators = Gauge('currentTransientValidators', 'currentTransientValidators')
        self.currentTransientBalance = Gauge('currentTransientBalance', 'currentTransientBalance')

        self.prevEpoch = Gauge('prevEpoch', 'prevEpoch')
        self.prevBeaconBalance = Gauge('prevBeaconBalance', 'prevBeaconBalance')
        self.prevBeaconValidators = Gauge('prevBeaconValidators', 'prevBeaconValidators')
        self.prevTimestamp = Gauge('prevTimestamp', 'prevTimestamp')
        self.prevBufferedBalance = Gauge('prevBufferedBalance', 'prevBufferedBalance')
        self.prevDepositedValidators = Gauge('prevDepositedValidators', 'prevDepositedValidators')
        self.prevActiveValidatorBalance = Gauge('prevActiveValidatorBalance', 'prevActiveValidatorBalance')
        self.prevTotalPooledEther = Gauge('prevTotalPooledEther', 'prevTotalPooledEther')
        self.prevTransientValidators = Gauge('prevTransientValidators', 'prevTransientValidators')
        self.prevTransientBalance = Gauge('prevTransientBalance', 'prevTransientBalance')

    def set_current_pool_metrics(self, metrics: PoolMetrics):
        self.currentEpoch.set(metrics.epoch)
        self.currentBeaconBalance.set(metrics.beaconBalance)
        self.currentBeaconValidators.set(metrics.beaconValidators)
        self.currentTimestamp.set(metrics.timestamp)
        self.currentBufferedBalance.set(metrics.bufferedBalance)
        self.currentDepositedValidators.set(metrics.depositedValidators)
        self.currentActiveValidatorBalance.set(metrics.activeValidatorBalance)
        self.currentTotalPooledEther.set(metrics.getTotalPooledEther())
        self.currentTransientValidators.set(metrics.getTransientValidators())
        self.currentTransientBalance.set(metrics.getTransientBalance())

        if metrics.validatorsKeysNumber is not None:
            self.validatorsKeysNumber.set(metrics.validatorsKeysNumber)

    def set_prev_pool_metrics(self, metrics: PoolMetrics):
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


metrics_exporter_state = MetricsExporterState()
