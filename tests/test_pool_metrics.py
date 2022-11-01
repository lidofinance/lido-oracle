from app.metrics import compare_pool_metrics, get_timestamp_by_epoch
from pool_metrics import PoolMetrics
import logging

ETH = 10**18
DAY = 24 * 60 * 60  # seconds


def test_pool_metrics_constants():
    pm = PoolMetrics()
    assert pm.MAX_APR == 0.15
    assert pm.MIN_APR == 0.01


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
    assert "Time delta: 0:02:03 or 123" in caplog.text  # 123 s
    assert "depositedValidators before:0 after:3 change:3" in caplog.text
    assert "beaconValidators before:0 after:1 change:1" in caplog.text
    assert "transientValidators before:0 after:2 change:2" in caplog.text  # =3-1
    assert "beaconBalance before:0 after:33000000000000000000 change:33000000000000000000" in caplog.text
    assert "bufferedBalance before:0 after:100000000000000000000 change:100000000000000000000" in caplog.text
    assert (
        "transientBalance before:0 after:64000000000000000000 change:64000000000000000000" in caplog.text
    )  # 2 validators * 32
    assert "totalPooledEther before:0 after:197000000000000000000" in caplog.text  # 33 + 2*32 + 100
    assert "The Lido has no funds under its control" in caplog.text
    assert "activeValidatorBalance now:0" in caplog.text


def test_compare_pool_metrics_loss(caplog):
    caplog.set_level(logging.INFO)
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = 1000001 * ETH
    prev.beaconValidators = 123
    prev.depositedValidators = 231
    prev.bufferedBalance = 456

    curr = PoolMetrics()
    curr.timestamp = 1600000001
    curr.beaconBalance = 1000000 * ETH  # loss
    curr.beaconValidators = 123
    curr.depositedValidators = 231
    curr.bufferedBalance = 123
    compare_pool_metrics(prev, curr)
    assert "Penalties will decrease totalPooledEther by" in caplog.text
    assert "Validators were either slashed or suffered penalties!" in caplog.text


def test_compare_pool_metrics_primitive_1percent_daily_too_high(caplog):
    caplog.set_level(logging.INFO)

    # Yesterday the Lido had beaconBalance = 100 ETH
    # and some number of validators (it won't change)
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = 100 * ETH
    prev.beaconValidators = 100000
    prev.depositedValidators = 100000
    prev.bufferedBalance = 0

    # Today the beaconBalance increased by 1%
    # Other numbers stay intact
    curr = PoolMetrics()
    curr.timestamp = 1600000000 + DAY
    # Interest gets calculated against cumulative balance of active validators.
    curr.activeValidatorBalance = 100 * ETH
    curr.beaconBalance = 101 * ETH
    curr.beaconValidators = 100000
    curr.depositedValidators = 100000
    curr.bufferedBalance = 0
    compare_pool_metrics(prev, curr)
    assert "Time delta: 1 day" in caplog.text
    assert "Rewards will increase Total pooled ethers by: 1.0000 %" in caplog.text
    assert "Daily staking reward rate for active validators: 1.00000000 %" in caplog.text
    assert "Staking APR for active validators: 365.0000 %" in caplog.text
    assert "Staking APR too high! Talk to your fellow oracles before submitting!" in caplog.text


def test_compare_pool_metrics_complex_reasonable_apr(caplog):
    """More complex case with queued validators, deposits
    and reasonable APR 1-10 percent"""
    caplog.set_level(logging.INFO)

    # Last year the Lido had beaconBalance of 1000 ETH
    # (31 validators * 32 ETH + 8 ETH rewards)
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = 1000 * ETH
    prev.beaconValidators = 31  # Doesn't matter
    prev.depositedValidators = 45  # Doesn't matter
    prev.bufferedBalance = 345 * ETH  # Doesn't matter

    # Since that time the active validators rewarded 100 ETH
    curr = PoolMetrics()
    curr.timestamp = 1600000000 + DAY * 365
    curr.beaconBalance = 1175 * ETH
    curr.activeValidatorBalance = 1175 * ETH
    curr.beaconValidators = 31  # Doesn't matter
    curr.depositedValidators = 67  # Doesn't matter
    curr.bufferedBalance = 678 * ETH  # Doesn't matter

    # so it produced 100.0/1100 ~= 9.0909% APR
    compare_pool_metrics(prev, curr)
    assert "Time delta: 365 days, 0:00:00 or 31536000 s" in caplog.text
    assert "Staking APR for active validators: 14.8936 %" in caplog.text
    # Output doesn't produce any warnings
    assert "Staking APR too " not in caplog.text


def test_compare_pool_metrics_complex_too_low_apr(caplog):
    """Too low APR"""
    caplog.set_level(logging.INFO)

    # Last year the Lido had beaconBalance of 1000 ETH
    # (31 validators * 32 ETH + 8 ETH rewards)
    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = 1000 * ETH
    prev.beaconValidators = 31  # Doesn't matter
    prev.depositedValidators = 45  # Doesn't matter
    prev.bufferedBalance = 345 * ETH  # Doesn't matter

    # Since that time the active validators rewarded 10 ETH
    curr = PoolMetrics()
    curr.timestamp = 1600000000 + DAY * 365
    curr.beaconBalance = 1010 * ETH
    curr.activeValidatorBalance = 1010 * ETH
    curr.beaconValidators = 31  # Doesn't matter
    curr.depositedValidators = 67  # Doesn't matter
    curr.bufferedBalance = 678 * ETH  # Doesn't matter

    # so it produced 10.0/110 ~= 0.99% APR.
    # It's below the bottom threshold. Warning printed.
    compare_pool_metrics(prev, curr)
    assert "Time delta: 365 days, 0:00:00 or 31536000 s" in caplog.text
    assert "Staking APR for active validators: 0.9901 %" in caplog.text
    assert "Staking APR too low!" in caplog.text


def test_compare_pool_metrics_validators_decrease(caplog):
    caplog.set_level(logging.INFO)

    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = 1 * ETH
    prev.beaconValidators = 31
    prev.depositedValidators = 45  # Doesn't matter
    prev.bufferedBalance = 1 * ETH  # Doesn't matter

    curr = PoolMetrics()
    curr.timestamp = 1600000000 + DAY  # Doesn't matter
    curr.beaconBalance = 1 * ETH  # Doesn't matter
    curr.activeValidatorBalance = 1 * ETH  # Doesn't matter
    curr.beaconValidators = 30
    curr.depositedValidators = 67  # Doesn't matter
    curr.bufferedBalance = 1 * ETH  # Doesn't matter

    compare_pool_metrics(prev, curr)
    assert "beaconValidators before:31 after:30 change:-1" in caplog.text
    assert "The number of beacon validators unexpectedly decreased!" in caplog.text


def test_compare_pool_metrics_0_balance_0_apr(caplog):
    caplog.set_level(logging.INFO)

    prev = PoolMetrics()
    prev.timestamp = 1600000000
    prev.beaconBalance = 0
    prev.beaconValidators = 0
    prev.depositedValidators = 45  # Doesn't matter
    prev.bufferedBalance = 1 * ETH  # Doesn't matter

    curr = PoolMetrics()
    curr.timestamp = 1600000000 + DAY  # Doesn't matter
    curr.beaconBalance = 0
    curr.activeValidatorBalance = 0
    curr.beaconValidators = 0
    curr.depositedValidators = 67  # Doesn't matter
    curr.bufferedBalance = 123 * ETH  # Doesn't matter

    compare_pool_metrics(prev, curr)
    assert "beaconBalance before:0 after:0 change:0" in caplog.text
    assert "activeValidatorBalance now:0" in caplog.text
    assert "Validators were rewarded 0 wei or 0.0 ETH" in caplog.text
    assert "Daily staking reward rate for active validators: 0.00000000 %" in caplog.text
    assert "Staking APR for active validators: 0.0000 %" in caplog.text
    assert "Staking APR too low! Talk to your fellow oracles before submitting!" in caplog.text
    assert (
        "Beacon balances stay intact (neither slashed nor rewarded). So this report won't have any economical impact on the pool."
        in caplog.text
    )


def test_get_timestamp_by_epoch():
    # Mainnet's spec
    beacon_spec = [225, 32, 12, 1606824023]
    # Genesis epoch of mainnet
    assert get_timestamp_by_epoch(beacon_spec, 0) == 1606824023
    # One of mainnet-reported epochs. Checked against beaconcha.in
    assert get_timestamp_by_epoch(beacon_spec, 8550) == 1610107223
    # One of latest epochs. Checked against beaconcha.in
    assert get_timestamp_by_epoch(beacon_spec, 8749) == 1610183639
