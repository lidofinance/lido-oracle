import pytest
from app.metrics import PoolMetrics, compare_pool_metrics
import logging


def test_pool_metrics_get_total_pooled_ether_empty():
    pm = PoolMetrics()
    assert pm.getTotalPooledEther() == 0
    assert pm.getTransientBalance() == 0
    assert pm.getTransientValidators() == 0


def test_pool_metrics_get_total_pooled_ether_non_empty():
    pm = PoolMetrics()
    pm.beaconBalance = int(65 * 1e18)
    pm.beaconValidators = 2
    pm.depositedValidators = 3
    pm.bufferedBalance = int(31 * 1e18)
    assert pm.getTotalPooledEther() == int(128 * 1e18)
    assert pm.getTransientValidators() == 1
    assert pm.getTransientBalance() == int(32 * 1e18)


def test_compare_pool_metrics_prev_null_tpe(caplog):
    caplog.set_level(logging.INFO)
    prev = PoolMetrics()
    curr = PoolMetrics()
    curr.beaconBalance = int(33 * 1e18)
    curr.beaconValidators = 1
    curr.depositedValidators = 3
    curr.bufferedBalance = int(100 * 1e18)
    curr.timestamp = 123
    compare_pool_metrics(prev, curr)
    assert "Time delta: 0:02:03 or 123" in caplog.text # 123 s
    assert "depositedValidators before:0 after:3 change:3" in caplog.text
    assert "beaconValidators before:0 after:1 change:1" in caplog.text
    assert "transientValidators before:0 after:2 change:2" in caplog.text # =3-1
    assert "beaconBalance before:0 after:33000000000000000000 change:33000000000000000000" in caplog.text
    assert "bufferedBalance before:0 after:100000000000000000000 change:100000000000000000000" in caplog.text
    assert "transientBalance before:0 after:64000000000000000000 change:64000000000000000000" in caplog.text  # 2 validators * 32
    assert "totalPooledEther before:0 after:197000000000000000000" in caplog.text # 33 + 2*32 + 100
    assert "The Lido has no funds under its control" in caplog.text


def test_compare_pool_metrics_loss(caplog):
    caplog.set_level(logging.INFO)
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = int(1000001 * 1e18)
    prev.beaconValidators = 123
    prev.depositedValidators = 231
    prev.bufferedBalance = 456

    curr = PoolMetrics()
    curr.timestamp = 1600000001
    curr.beaconBalance = int(1000000 * 1e18) # loss
    curr.beaconValidators = 123
    curr.depositedValidators = 231
    curr.bufferedBalance = 123
    compare_pool_metrics(prev, curr)
    assert "Penalties will decrease totalPooledEther by" in caplog.text
    assert "Validators were either slashed or suffered penalties!" in caplog.text


def test_compare_pool_metrics_simplest_daily_to_apr(caplog):
    """Simplest case. No queued funds, no deposits, all funds are on beacon.
    0.1% daily interest = 36.5 APR"""
    caplog.set_level(logging.INFO)
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = int(1000000 * 1e18)
    prev.beaconValidators = 100000
    prev.depositedValidators = 100000
    prev.bufferedBalance = 0

    curr = PoolMetrics()
    curr.timestamp = 1600000000 + 24 * 60 * 60 # + 1 day
    curr.beaconBalance = int(1001000 * 1e18) # + 0.01% per day
    curr.beaconValidators = 100000
    curr.depositedValidators = 100000
    curr.bufferedBalance = 0
    compare_pool_metrics(prev, curr)
    assert "Time delta: 1 day" in caplog.text
    assert "Rewards will increase Total pooled ethers by: 0.1000 %" in caplog.text
    assert "Daily interest rate: 0.10000000 %" in caplog.text
    assert "Expected APR: 36.5000 %" in caplog.text


def test_compare_pool_metrics_complex_case_apr(caplog):
    """More complex case with queued validators, deposits
    0.1% daily interest = 36.5 APR"""
    caplog.set_level(logging.INFO)
    """totalPooledEther = 1000000 ETH:
            on beacon = 500000 (15620 validators * 32 + some tiny rewards)
            in activation queue = 400000 (12500 validators * 32)
            in buffer = 100000
    """
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = int(500000 * 1e18)
    prev.beaconValidators = 15620
    prev.depositedValidators = 15620 + 12500 # see comments above
    prev.bufferedBalance = int(100000 * 1e18)

    assert prev.getTotalPooledEther() == int(1000000 * 1e18)

    curr = PoolMetrics()
    curr.timestamp = 1600000000 + 24 * 60 * 60 # + 1 day
    curr.bufferedBalance = int(200000 * 1e18) # increased by users' submissions but ignored
    curr.depositedValidators = 30000 # increased by deposits but ignored
    curr.beaconValidators = 20000 # increased by validators activation but ignored
    # beacon balance increased by appeared validators + rewards
    # and only rewards get calculated in APR
    #
    # appeared_validators = 20000 - 15620 = 4380
    # increase_by_appeared_validators = appeared_validators * 32 = 140160
    curr.beaconBalance = int((501000 + 140160) * 1e18) # + 0.01% reward per day

    compare_pool_metrics(prev, curr)
    assert "Time delta: 1 day" in caplog.text
    assert "Rewards will increase Total pooled ethers by: 0.1000 %" in caplog.text
    assert "Daily interest rate: 0.10000000 %" in caplog.text
    assert "Expected APR: 36.5000 %" in caplog.text
