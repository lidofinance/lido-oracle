# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import logging
import datetime

from web3 import Web3

from contracts import get_validators_keys
from pool_metrics import PoolMetrics
from prometheus_metrics import metrics_exporter_state


def get_previous_metrics(w3, pool, oracle, beacon_spec, from_block=0) -> PoolMetrics:
    """Since the contract lacks a method that returns the time of last report and the reported numbers
    we are using web3.py filtering to fetch it from the contract events."""
    logging.info('Getting previously reported numbers (will be fetched from events)...')
    genesis_time = beacon_spec[3]
    result = PoolMetrics()
    result.depositedValidators, result.beaconValidators, result.beaconBalance = pool.functions.getBeaconStat().call()
    result.bufferedBalance = pool.functions.getBufferedEther().call()

    # Calculate the earliest block to limit scanning depth
    SECONDS_PER_ETH1_BLOCK = 14
    latest_block = w3.eth.getBlock('latest')
    from_block = max(from_block, int((latest_block['timestamp'] - genesis_time) / SECONDS_PER_ETH1_BLOCK))
    step = 10000
    # Try to fetch and parse last 'Completed' event from the contract.
    for end in range(latest_block['number'], from_block, -step):
        start = max(end - step + 1, from_block)
        events = oracle.events.Completed.getLogs(fromBlock=start, toBlock=end)
        if events:
            event = events[-1]
            result.epoch = event['args']['epochId']
            result.blockNumber = event.blockNumber
            break

    # If the epoch has been assigned from the last event (not the first run)
    if result.epoch:
        result.timestamp = get_timestamp_by_epoch(beacon_spec, result.epoch)
    else:
        # If it's the first run, we set timestamp to genesis time
        result.timestamp = genesis_time
    return result


def get_light_current_metrics(w3, beacon, pool, oracle, beacon_spec):
    """Fetch current frame, buffered balance and epoch"""
    epochs_per_frame = beacon_spec[0]
    partial_metrics = PoolMetrics()
    partial_metrics.blockNumber = w3.eth.getBlock('latest')['number']  # Get the epoch that is finalized and reportable
    current_frame = oracle.functions.getCurrentFrame().call()
    potentially_reportable_epoch = current_frame[0]
    logging.info(f'Potentially reportable epoch: {potentially_reportable_epoch} (from ETH1 contract)')
    finalized_epoch_beacon = beacon.get_finalized_epoch()
    # For Web3 client
    # finalized_epoch_beacon = int(beacon.get_finality_checkpoint()['data']['finalized']['epoch'])
    logging.info(f'Last finalized epoch: {finalized_epoch_beacon} (from Beacon)')
    partial_metrics.epoch = min(
        potentially_reportable_epoch, (finalized_epoch_beacon // epochs_per_frame) * epochs_per_frame
    )
    partial_metrics.timestamp = get_timestamp_by_epoch(beacon_spec, partial_metrics.epoch)
    partial_metrics.depositedValidators = pool.functions.getBeaconStat().call()[0]
    partial_metrics.bufferedBalance = pool.functions.getBufferedEther().call()
    return partial_metrics


def get_full_current_metrics(
    w3: Web3, pool, beacon, beacon_spec, partial_metrics, consider_withdrawals_from_epoch
) -> PoolMetrics:
    """The oracle fetches all the required states from ETH1 and ETH2 (validator balances)"""
    slot = beacon.get_slot_for_report(partial_metrics.epoch * beacon_spec[1], beacon_spec[0], beacon_spec[1])
    logging.info(f'Reportable state: epoch:{partial_metrics.epoch} slot:{slot}')
    validators_keys = get_validators_keys(w3)
    logging.info(f'Total validator keys in registry: {len(validators_keys)}')
    full_metrics = partial_metrics
    full_metrics.validatorsKeysNumber = len(validators_keys)
    (
        full_metrics.beaconBalance,
        full_metrics.beaconValidators,
        full_metrics.activeValidatorBalance,
    ) = beacon.get_balances(slot, validators_keys)

    logging.info(
        f'Lido validators\' sum. balance on Beacon: '
        f'{full_metrics.beaconBalance} wei or {full_metrics.beaconBalance / 1e18} ETH'
    )

    block_number = beacon.get_block_by_beacon_slot(slot)
    withdrawal_credentials = w3.toHex(pool.functions.getWithdrawalCredentials().call(block_identifier=block_number))
    full_metrics.withdrawalVaultBalance = w3.eth.get_balance(
        w3.toChecksumAddress(withdrawal_credentials.replace('0x010000000000000000000000', '0x')),
        block_identifier=block_number
    )

    logging.info(
        f'Withdrawal vault balance: {full_metrics.withdrawalVaultBalance} wei or {full_metrics.withdrawalVaultBalance / 1e18} ETH'
    )

    corrected_balance = full_metrics.beaconBalance + full_metrics.withdrawalVaultBalance
    logging.info(
        f'Lido validators\' sum. balance on Beacon corrected by withdrawals: '
        f'{corrected_balance} wei or {corrected_balance / 1e18} ETH'
    )

    if full_metrics.epoch >= int(consider_withdrawals_from_epoch):
        full_metrics.beaconBalance = corrected_balance
        logging.info('Corrected balance on Beacon is accounted')
    else:
        remaining = int(consider_withdrawals_from_epoch) - full_metrics.epoch
        logging.info(f'Corrected balance on Beacon is NOT accounted yet. Remaining epochs before account: {remaining}')

    logging.info(f'Lido validators visible on Beacon: {full_metrics.beaconValidators}')
    return full_metrics


def compare_pool_metrics(previous: PoolMetrics, current: PoolMetrics) -> bool:
    """Describes the economics of metrics change.
    Helps the Node operator to understand the effect of firing composed TX
    Returns true on suspicious metrics"""
    warnings = False
    assert previous.DEPOSIT_SIZE == current.DEPOSIT_SIZE
    DEPOSIT_SIZE = previous.DEPOSIT_SIZE
    delta_seconds = current.timestamp - previous.timestamp
    metrics_exporter_state.deltaSeconds.set(delta_seconds)  # fixme: get rid of side effects
    appeared_validators = current.beaconValidators - previous.beaconValidators
    metrics_exporter_state.appearedValidators.set(appeared_validators)
    logging.info(f'Time delta: {datetime.timedelta(seconds=delta_seconds)} or {delta_seconds} s')
    logging.info(
        f'depositedValidators before:{previous.depositedValidators} after:{current.depositedValidators} change:{current.depositedValidators - previous.depositedValidators}'
    )

    if current.beaconValidators < previous.beaconValidators:
        warnings = True
        logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        logging.warning('The number of beacon validators unexpectedly decreased!')
        logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

    logging.info(
        f'beaconValidators before:{previous.beaconValidators} after:{current.beaconValidators} change:{appeared_validators}'
    )
    logging.info(
        f'transientValidators before:{previous.getTransientValidators()} after:{current.getTransientValidators()} change:{current.getTransientValidators() - previous.getTransientValidators()}'
    )
    logging.info(
        f'beaconBalance before:{previous.beaconBalance} after:{current.beaconBalance} change:{current.beaconBalance - previous.beaconBalance}'
    )
    logging.info(
        f'bufferedBalance before:{previous.bufferedBalance} after:{current.bufferedBalance} change:{current.bufferedBalance - previous.bufferedBalance}'
    )
    logging.info(
        f'transientBalance before:{previous.getTransientBalance()} after:{current.getTransientBalance()} change:{current.getTransientBalance() - previous.getTransientBalance()}'
    )
    logging.info(f'totalPooledEther before:{previous.getTotalPooledEther()} after:{current.getTotalPooledEther()} ')
    logging.info(f'activeValidatorBalance now:{current.activeValidatorBalance} ')

    reward_base = appeared_validators * DEPOSIT_SIZE + previous.beaconBalance
    reward = current.beaconBalance - reward_base
    if not previous.getTotalPooledEther():
        logging.info(
            'The Lido has no funds under its control. Probably the system has been just deployed and has never been deposited'
        )
        return

    if not delta_seconds:
        logging.info('No time delta between current and previous epochs. Skip APR calculations.')
        assert reward == 0
        assert current.beaconValidators == previous.beaconValidators
        assert current.beaconBalance == current.beaconBalance
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
        logging.info(
            f'Rewards will increase Total pooled ethers by: {reward / previous.getTotalPooledEther() * 100:.4f} %'
        )
        logging.info(f'Daily staking reward rate for active validators: {daily_reward_rate * 100:.8f} %')
        logging.info(f'Staking APR for active validators: {apr * 100:.4f} %')
        if apr > current.MAX_APR:
            warnings = True
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            logging.warning('Staking APR too high! Talk to your fellow oracles before submitting!')
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')

        if apr < current.MIN_APR:
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
        logging.info(
            'Beacon balances stay intact (neither slashed nor rewarded). So this report won\'t have any economical impact on the pool.'
        )

    return warnings


def get_timestamp_by_epoch(beacon_spec, epoch_id):
    """Required to calculate time-bound values such as APR"""
    slots_per_epoch = beacon_spec[1]
    seconds_per_slot = beacon_spec[2]
    genesis_time = beacon_spec[3]
    return genesis_time + slots_per_epoch * seconds_per_slot * epoch_id
