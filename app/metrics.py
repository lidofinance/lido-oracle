# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import logging
import datetime
from contracts import get_validators_keys


class PoolMetrics:
    DEPOSIT_SIZE = int(32 * 1e18)
    MAX_APR = 0.15
    MIN_APR = 0.01
    epoch = 0
    beaconBalance = 0
    beaconValidators = 0
    timestamp = 0
    bufferedBalance = 0
    depositedValidators = 0
    activeValidatorBalance = 0

    def getTotalPooledEther(self):
        return self.bufferedBalance + self.beaconBalance + self.getTransientBalance()

    def getTransientValidators(self):
        assert(self.depositedValidators >= self.beaconValidators)
        return self.depositedValidators - self.beaconValidators

    def getTransientBalance(self):
        return self.getTransientValidators() * self.DEPOSIT_SIZE


def get_previous_metrics(w3, pool, oracle, beacon_spec, from_block=0):
    """Since the contract lacks a method that returns the time of last report and the reported numbers
    we are using web3.py filtering to fetch it from the contract events."""
    logging.info('Getting previously reported numbers (will be fetched from events)...')
    genesis_time = beacon_spec[3]
    result = PoolMetrics()
    result.depositedValidators, result.beaconValidators, result.beaconBalance = pool.functions.getBeaconStat().call()
    result.bufferedBalance = pool.functions.getBufferedEther().call()

    # Calculate earliest block to limit scanning depth
    SECONDS_PER_ETH1_BLOCK = 14
    latest_block = w3.eth.getBlock('latest')
    from_block = max(from_block, int((latest_block['timestamp']-genesis_time)/SECONDS_PER_ETH1_BLOCK))
    step = 10000
    # Try to fetch and parse last 'Completed' event from the contract.
    for end in range(latest_block['number'], from_block, -step):
        start = max(end - step + 1, from_block)
        events = oracle.events.Completed.getLogs(fromBlock=start, toBlock=end)
        if events:
            event = events[-1]
            result.epoch = event['args']['epochId']
            break

    # If the epoch has been assigned from the last event (not the first run)
    if result.epoch:
        result.timestamp = get_timestamp_by_epoch(beacon_spec, result.epoch)
    else:
        # If it's the first run, we set timestamp to genesis time
        result.timestamp = genesis_time
    return result


def get_current_metrics(w3, beacon, pool, oracle, registry, beacon_spec):
    epochs_per_frame = beacon_spec[0]
    slots_per_epoch = beacon_spec[1]
    result = PoolMetrics()
    # Get the the epoch that is both finalized and reportable
    current_frame = oracle.functions.getCurrentFrame().call()
    potentially_reportable_epoch = current_frame[0]
    logging.info(f'Potentially reportable epoch: {potentially_reportable_epoch} (from ETH1 contract)')
    finalized_epoch_beacon = beacon.get_finalized_epoch()
    logging.info(f'Last finalized epoch: {finalized_epoch_beacon} (from Beacon)')
    result.epoch = min(potentially_reportable_epoch,
                       (finalized_epoch_beacon // epochs_per_frame) * epochs_per_frame)
    slot = result.epoch * slots_per_epoch
    logging.info(f'Reportable state: epoch:{result.epoch} slot:{slot}')

    validators_keys = get_validators_keys(registry)
    logging.info(f'Total validator keys in registry: {len(validators_keys)}')

    result.timestamp = get_timestamp_by_epoch(beacon_spec, result.epoch)
    result.beaconBalance, result.beaconValidators, result.activeValidatorBalance = beacon.get_balances(
        slot, validators_keys)
    result.depositedValidators = pool.functions.getBeaconStat().call()[0]
    result.bufferedBalance = pool.functions.getBufferedEther().call()
    logging.info(f'Lido validators\' sum. balance on Beacon: {result.beaconBalance} wei or {result.beaconBalance/1e18} ETH')
    logging.info(f'Lido validators visible on Beacon: {result.beaconValidators}')
    return result


def compare_pool_metrics(previous, current):
    """Describes the economics of metrics change.
    Helps the Node operator to understand the effect of firing composed TX
    Returns true on suspicious metrics"""
    warnings = False
    assert previous.DEPOSIT_SIZE == current.DEPOSIT_SIZE
    DEPOSIT_SIZE = previous.DEPOSIT_SIZE
    delta_seconds = current.timestamp - previous.timestamp
    appeared_validators = current.beaconValidators - previous.beaconValidators
    logging.info(f'Time delta: {datetime.timedelta(seconds = delta_seconds)} or {delta_seconds} s')
    logging.info(f'depositedValidators before:{previous.depositedValidators} after:{current.depositedValidators} change:{current.depositedValidators - previous.depositedValidators}')

    if current.beaconValidators < previous.beaconValidators:
        warnings = True
        logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        logging.warning('The number of beacon validators unexpectedly decreased!')
        logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

    logging.info(f'beaconValidators before:{previous.beaconValidators} after:{current.beaconValidators} change:{appeared_validators}')
    logging.info(f'transientValidators before:{previous.getTransientValidators()} after:{current.getTransientValidators()} change:{current.getTransientValidators() - previous.getTransientValidators()}')
    logging.info(f'beaconBalance before:{previous.beaconBalance} after:{current.beaconBalance} change:{current.beaconBalance - previous.beaconBalance}')
    logging.info(f'bufferedBalance before:{previous.bufferedBalance} after:{current.bufferedBalance} change:{current.bufferedBalance - previous.bufferedBalance}')
    logging.info(f'transientBalance before:{previous.getTransientBalance()} after:{current.getTransientBalance()} change:{current.getTransientBalance() - previous.getTransientBalance()}')
    logging.info(f'totalPooledEther before:{previous.getTotalPooledEther()} after:{current.getTotalPooledEther()} ')
    logging.info(f'activeValidatorBalance now:{current.activeValidatorBalance} ')

    reward_base = appeared_validators * DEPOSIT_SIZE + previous.beaconBalance
    reward = current.beaconBalance - reward_base
    if not previous.getTotalPooledEther():
        logging.info('The Lido has no funds under its control. Probably the system has been just deployed and has never been deposited')
        return

    if not delta_seconds:
        logging.info('No time delta between current and previous epochs. Skip APR calculations.')
        assert(reward == 0)
        assert(current.beaconValidators == previous.beaconValidators)
        assert(current.beaconBalance == current.beaconBalance)
        return

    # APR calculation
    if current.activeValidatorBalance == 0:
        daily_reward_rate = 0
    else:
        days = delta_seconds / 60 / 60 / 24
        daily_reward_rate = reward / current.activeValidatorBalance / days

    apr = daily_reward_rate * 365

    if reward >= 0:
        logging.info(f'Validators were rewarded {reward} wei or {reward/1e18} ETH')
        logging.info(f'Rewards will increase Total pooled ethers by: {reward / previous.getTotalPooledEther() * 100:.4f} %')
        logging.info(f'Daily staking reward rate for active validators: {daily_reward_rate * 100:.8f} %')
        logging.info(f'Staking APR for active validators: {apr * 100:.4f} %')
        if (apr > current.MAX_APR):
            warnings = True
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            logging.warning('Staking APR too high! Talk to your fellow oracles before submitting!')
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

        if (apr < current.MIN_APR):
            warnings = True
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            logging.warning('Staking APR too low! Talk to your fellow oracles before submitting!')
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

    else:
        warnings = True
        logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        logging.warning(f'Penalties will decrease totalPooledEther by {-reward} wei or {-reward/1e18} ETH')
        logging.warning('Validators were either slashed or suffered penalties!')
        logging.warning('Talk to your fellow oracles before submitting!')
        logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

    if reward == 0:
        logging.info('Beacon balances stay intact (neither slashed nor rewarded). So this report won\'t have any economical impact on the pool.')

    return warnings


def get_timestamp_by_epoch(beacon_spec, epoch_id):
    """Required to calculate time-bound values such as APR"""
    slots_per_epoch = beacon_spec[1]
    seconds_per_slot = beacon_spec[2]
    genesis_time = beacon_spec[3]
    return genesis_time + slots_per_epoch * seconds_per_slot * epoch_id
