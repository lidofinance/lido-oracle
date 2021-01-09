# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import logging
import datetime
from contracts import get_validators_keys
from enum import Enum

class Frame:
    DEPOSIT_SIZE = int(32 * 1e18)
    epoch = 0
    timestamp = 0
    bufferedBalance = 0
    depositedValidators = 0
    activeValidatorBalance = 0
    slot = 0
    beaconBalance = 0
    beaconValidators = 0

    def getTotalPooledEther(self):
        return self.bufferedBalance + self.beaconBalance + self.getTransientBalance()

    def getTransientValidators(self):
        assert(self.depositedValidators >= self.beaconValidators)
        return self.depositedValidators - self.beaconValidators

    def getTransientBalance(self):
        return self.getTransientValidators() * self.DEPOSIT_SIZE


class PoolMetric:
    MAX_APR = 0.15
    MIN_APR = 0.01
    delta_seconds = 0
    appeared_validators = 0
    reportable_epoch = None
    warnings = []
    apr = None

    class State(Enum):
        INIT = 0 # after initialisation, before getting prev_frame
        HAS_PFRAME = 1 # after got prev_frame, before figuring out reportable epoch id
        HAS_REPORTABLE_EPOCH_ID = 2 # after figuring out reportable epoch id before minimal stat fetch
        HAS_CURR_FRM_OVERALL = 3 # after fetching overall numbers of reportable frame
        HAS_CURR_FRM_DETAILS = 4 # after keys and beacon balances got fetched
        TX_READY = 5 # Report values are prepared, TX is composed and executed locally
        TX_SIGNED = 6 # Tx signed by the private key
        TX_SENT = 7 # TX serialized via web3
        TX_MINED = 8 # TX got included into the block (receipt available)
        TX_CONFIRMED = 9 # TX got confirmations, considered final
        NOOP = 10 # Graceful final state when everything is done.
        ERR_STOP = -1 # Final state after unrecoverable failure. Print warnings and exit.

    def __init__(self, w3, pool, oracle, registry, beacon_spec, from_block=0):
        self.prev_frm = Frame()
        self.curr_frm = Frame()
        self.w3 = w3
        self.pool = pool
        self.oracle = oracle
        self.registry = registry
        self.epochs_per_frame = beacon_spec[0]
        self.slots_per_epoch = beacon_spec[1]
        self.seconds_per_slot = beacon_spec[2]
        self.genesis_time = beacon_spec[3]
        self.from_block = from_block
        self.state = self.State.INIT
    
    def _get_timestamp_by_epoch(epoch_id):
        """Required to calculate time-bound values such as APR"""
        return self.genesis_time + self.slots_per_epoch * self.seconds_per_slot * epoch_id
    
    def get_prev_frame(self):
        """Since the contract lacks a method that returns the time of last report and the reported numbers
        we are using web3.py filtering to fetch it from the contract events."""
        assert self.state == self.State.INIT
        logging.info('Getting previously reported numbers (will be fetched from events)...')
        self.prev_frm.depositedValidators, self.prev_frm.beaconValidators, self.prev_frm.beaconBalance = pool.functions.getBeaconStat().call()
        self.prev_frm.bufferedBalance = self.pool.functions.getBufferedEther().call()

        # Calculate earliest block to limit scanning depth
        SECONDS_PER_ETH1_BLOCK = 14
        latest_block = self.w3.eth.getBlock('latest')
        from_block = max(from_block, int((latest_block['timestamp']-genesis_time)/SECONDS_PER_ETH1_BLOCK))
        step = 10000
        # Try to fetch and parse last 'Completed' event from the contract.
        for end in range(latest_block['number'], self.from_block, -step):
            start = max(end - step + 1, self.from_block)
            events = oracle.events.Completed.getLogs(fromBlock=start, toBlock=end)
            if events:
                event = events[-1]
                self.prev_frm.epoch = event['args']['epochId']
                self.prev_frm.timestamp = get_timestamp_by_epoch(self.prev_frm.epoch)
                break
        else:
            self.prev_frm.timestamp = genesis_time
        
        if not logging.getTotalPooledEther():
            self.warnings.extend('The Lido has no funds under its control. Probably the system has been just deployed and has never been deposited')
            self.state = self.State.ERR_STOP
        return
        self.state = self.State.HAS_PFRAME

    def get_reportable_epoch(self):
        # Get the the epoch that is both finalized and reportable
        assert self.state == self.State.HAS_PFRAME
        current_frame = oracle.functions.getCurrentFrame().call()
        potentially_reportable_epoch = current_frame[0]
        logging.info(f'Potentially reportable epoch: {potentially_reportable_epoch} (from ETH1 contract)')
        finalized_epoch_beacon = beacon.get_finalized_epoch()
        logging.info(f'Last finalized epoch: {finalized_epoch_beacon} (from Beacon)')
        self.curr_frm.epoch = min(potentially_reportable_epoch,
                        (finalized_epoch_beacon // epochs_per_frame) * epochs_per_frame)
        self.curr_frm.timestamp = get_timestamp_by_epoch(self.beacon_spec, self.curr_frm.epoch)
        self.state = self.State.HAS_REPORTABLE_EPOCH_ID

    def get_curr_frame_overall(self):
        """Fetch overall statistics for reportable frame. Fast."""
        assert self.state == self.State.HAS_REPORTABLE_EPOCH_ID
        self.delta_seconds = self.curr_frm.timestamp - self.prev_frm.timestamp
        self.appeared_validators = current.beaconValidators - previous.beaconValidators
        logging.info(f'Time delta: {datetime.timedelta(seconds = self.delta_seconds)} or {self.delta_seconds} s')
        if not self.delta_seconds:
            logging.info('No time delta between current and previous epochs.')
        self.curr_frm.depositedValidators = pool.functions.getBeaconStat().call()[0]
        self.curr_frm.bufferedBalance = pool.functions.getBufferedEther().call()
        logging.info(f'depositedValidators before:{previous.depositedValidators} after:{current.depositedValidators} change:{current.depositedValidators - previous.depositedValidators}')
        self.state = self.State.HAS_CURR_FRM_OVERALL
    
    def get_curr_frame_details(self):
        assert self.state == self.State.HAS_CURR_FRM_OVERALL
        validators_keys = get_validators_keys(self.registry)
        logging.info(f'Total validator keys in registry: {len(validators_keys)}')
        self.curr_frm.slot = self.curr_frm.epoch * slots_per_epoch
        logging.info(f'Reportable state: epoch:{self.curr_frm.epoch} slot:{self.curr_frm.slot}')
        self.curr_frm.beaconBalance, self.curr_frm.beaconValidators, self.curr_frm.activeValidatorBalance = beacon.get_balances(
            self.curr_frm.slot, validators_keys)
        logging.info(f'Lido validators\' sum. balance on Beacon: {self.curr_frm.beaconBalance} wei or {self.curr_frm.beaconBalance/1e18} ETH')
        logging.info(f'Lido validators visible on Beacon: {self.curr_frm.beaconValidators}')
        self.state = self.State.HAS_CURR_FRM_DETAILS
    
    def calculate_reward(self):
        """Describes the economics of metrics change.
        Helps the Node operator to understand the effect of firing composed TX
        Returns true on suspicious metrics"""
        assert self.state == self.State.HAS_CURR_FRM_DETAILS
        if current.beaconValidators < previous.beaconValidators:
            self.warnings.extend('The number of beacon validators unexpectedly decreased!')
        reward_base = appeared_validators * DEPOSIT_SIZE + previous.beaconBalance
        reward = current.beaconBalance - reward_base

        if current.activeValidatorBalance == 0:
            daily_reward_rate = 0
        else:
            days = delta_seconds / 60 / 60 / 24
            daily_reward_rate = reward / current.activeValidatorBalance / days
        apr = daily_reward_rate * 365

        logging.info(f'beaconValidators before:{previous.beaconValidators} after:{current.beaconValidators} change:{appeared_validators}')
        logging.info(f'transientValidators before:{previous.getTransientValidators()} after:{current.getTransientValidators()} change:{current.getTransientValidators() - previous.getTransientValidators()}')
        logging.info(f'beaconBalance before:{previous.beaconBalance} after:{current.beaconBalance} change:{current.beaconBalance - previous.beaconBalance}')
        logging.info(f'bufferedBalance before:{previous.bufferedBalance} after:{current.bufferedBalance} change:{current.bufferedBalance - previous.bufferedBalance}')
        logging.info(f'transientBalance before:{previous.getTransientBalance()} after:{current.getTransientBalance()} change:{current.getTransientBalance() - previous.getTransientBalance()}')
        logging.info(f'totalPooledEther before:{previous.getTotalPooledEther()} after:{current.getTotalPooledEther()} ')
        logging.info(f'activeValidatorBalance now:{current.activeValidatorBalance} ')

        if reward >= 0:
            logging.info(f'Validators were rewarded {reward} wei or {reward/1e18} ETH')
            logging.info(f'Rewards will increase Total pooled ethers by: {reward / previous.getTotalPooledEther() * 100:.4f} %')
            logging.info(f'Daily staking reward rate for active validators: {daily_reward_rate * 100:.8f} %')
            logging.info(f'Staking APR for active validators: {apr * 100:.4f} %')
            if (apr > current.MAX_APR):
                self.warnings.extend('Staking APR too high! Talk to your fellow oracles before submitting!')
                self.state = self.State.ERR_STOP

            if (apr < current.MIN_APR):
                self.warnings.extend('Staking APR too low! Talk to your fellow oracles before submitting!')
                self.state = self.State.ERR_STOP

        else:
            self.warnings.extend('Penalties will decrease totalPooledEther by {-reward} wei or {-reward/1e18} ETH')
            self.warnings.extend('Validators were either slashed or suffered penalties! Talk to your fellow oracles before submitting!')
            self.state = self.State.ERR_STOP

    if reward == 0:
        logging.info('Beacon balances stay intact (neither slashed nor rewarded). So this report won\'t have any economical impact on the pool.')


    def print_finally(self):
        assert self.state in [ self.State.ERR_STOP, self.State.NOOP ]
        for warning_msg in self.warnings:
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            logging.warning(warning_msg)
            logging.warning('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
