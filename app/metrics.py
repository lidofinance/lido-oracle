# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import logging
import datetime

class PoolMetrics:
    DEPOSIT_SIZE = int(32 * 1e18)
    epoch = 0
    beaconBalance = 0
    beaconValidators = 0
    timestamp = 0
    bufferedBalance = 0
    depositedValidators = 0

    def getTotalPooledEther(self):
        return self.bufferedBalance + self.beaconBalance + self.getTransientBalance()

    def getTransientValidators(self):
        assert(self.depositedValidators >= self.beaconValidators)
        return self.depositedValidators - self.beaconValidators

    def getTransientBalance(self):
        return self.getTransientValidators() * self.DEPOSIT_SIZE


def compare_pool_metrics(previous, current):
    """Describes the economics of metrics change.
    Helps the Node operator to understand the effect of firing composed TX"""
    assert previous.DEPOSIT_SIZE == current.DEPOSIT_SIZE
    DEPOSIT_SIZE = previous.DEPOSIT_SIZE
    delta_seconds = current.timestamp - previous.timestamp
    appeared_validators = current.beaconValidators - previous.beaconValidators
    logging.info(f'Time delta: {datetime.timedelta(seconds = delta_seconds)} or {delta_seconds} s')
    logging.info(f'depositedValidators before:{previous.depositedValidators} after:{current.depositedValidators} change:{current.depositedValidators - previous.depositedValidators}')
    if current.beaconValidators < previous.beaconValidators:
        logging.warning('The number of beacon validators unexpectedly decreased!')
    logging.info(f'beaconValidators before:{previous.beaconValidators} after:{current.beaconValidators} change:{appeared_validators}')
    logging.info(f'transientValidators before:{previous.getTransientValidators()} after:{current.getTransientValidators()} change:{current.getTransientValidators() - previous.getTransientValidators()}')
    logging.info(f'beaconBalance before:{previous.beaconBalance} after:{current.beaconBalance} change:{current.beaconBalance - previous.beaconBalance}')
    logging.info(f'bufferedBalance before:{previous.bufferedBalance} after:{current.bufferedBalance} change:{current.bufferedBalance - previous.bufferedBalance}')
    logging.info(f'transientBalance before:{previous.getTransientBalance()} after:{current.getTransientBalance()} change:{current.getTransientBalance() - previous.getTransientBalance()}')
    logging.info(f'totalPooledEther before:{previous.getTotalPooledEther()} after:{current.getTotalPooledEther()} ')
    reward_base = appeared_validators * DEPOSIT_SIZE + previous.beaconBalance
    reward = current.beaconBalance - reward_base
    if not previous.getTotalPooledEther():
        logging.info(f'The Lido has no funds under its control. Probably the system has been just deployed and has never been deposited')
        return

    # APR calculation
    days = delta_seconds / 60 / 60 / 24
    daily_interest_rate = reward / previous.getTotalPooledEther() / days
    apr = daily_interest_rate * 365

    if reward > 0:
        logging.info(f'Validators were rewarded {reward} wei or {reward/1e18} ETH')
        logging.info(f'Rewards will increase Total pooled ethers by: {reward / previous.getTotalPooledEther() * 100:.4f} %')
        logging.info(f'Daily interest rate: {daily_interest_rate * 100:.8f} %')
        logging.info(f'Expected APR: {apr * 100:.4f} %')
    elif reward < 0:
        logging.warning(f'Penalties will decrease totalPooledEther by {-reward} wei or {-reward/1e18} ETH')
        logging.warning('Validators were either slashed or suffered penalties!')
    else:
        logging.info('Beacon balances stay intact (neither slashed nor rewarded). So this report won\'t have any economical impact on the pool.')