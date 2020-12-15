# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import json
import logging
import os
import datetime
import time

from web3 import Web3, WebsocketProvider, HTTPProvider
from web3.exceptions import SolidityError

from beacon import get_beacon
from contracts import get_validators_keys
from log import init_log

init_log()
logger = logging.getLogger(__name__)

VERSION_JSON_PATH = os.environ.get('VERSION_JSON_PATH', '/version.json')
if os.path.exists(VERSION_JSON_PATH):
    with open(VERSION_JSON_PATH) as version_file:
        version_info = json.load(version_file)
    logging.info('version: %s' % version_info.get('version'))
    logging.info('commit_message: %s' % version_info.get('commit_message'))
    logging.info('commit_hash: %s' % version_info.get('commit_hash'))
    logging.info('commit_datetime: %s' % version_info.get('commit_datetime'))
    logging.info('build_datetime: %s' % version_info.get('build_datetime'))
    logging.info('tags: %s' % version_info.get('tags'))
    logging.info('branch: %s' % version_info.get('branch'))
else:
    logging.info('version json file does not exist')

envs = [
    'ETH1_NODE',
    'BEACON_NODE',
    'POOL_CONTRACT',
]
missing = []
for env in envs:
    if env not in os.environ or os.environ[env] == '':
        missing.append(env)
        logging.error('Mandatory variable %s is missing', env)

if missing:
    exit(1)

ARTIFACTS_DIR = './assets'
ORACLE_ARTIFACT_FILE = 'LidoOracle.json'
POOL_ARTIFACT_FILE = 'Lido.json'
REGISTRY_ARTIFACT_FILE = 'NodeOperatorsRegistry.json'
DEFAULT_SLEEP = 60
DEFAULT_GAS_LIMIT = 1_500_000

eth1_provider = os.environ['ETH1_NODE']
beacon_provider = os.environ['BEACON_NODE']
pool_address = os.environ['POOL_CONTRACT']
if not Web3.isChecksumAddress(pool_address):
    pool_address = Web3.toChecksumAddress(pool_address)
oracle_abi_path = os.path.join(ARTIFACTS_DIR, ORACLE_ARTIFACT_FILE)
pool_abi_path = os.path.join(ARTIFACTS_DIR, POOL_ARTIFACT_FILE)
registry_abi_path = os.path.join(ARTIFACTS_DIR, REGISTRY_ARTIFACT_FILE)
member_privkey = os.getenv('MEMBER_PRIV_KEY')
await_time_in_sec = int(os.getenv('SLEEP', DEFAULT_SLEEP))

run_as_daemon = int(os.getenv('DAEMON', 0))

dry_run = member_privkey is None

GAS_LIMIT = int(os.getenv('GAS_LIMIT', DEFAULT_GAS_LIMIT))

if eth1_provider.startswith('http'):
    provider = HTTPProvider(eth1_provider)
elif eth1_provider.startswith('ws'):
    provider = WebsocketProvider(eth1_provider)
else:
    logging.error('Unsupported ETH provider!')
    exit(1)

w3 = Web3(provider)

if not w3.isConnected():
    logging.error('ETH node connection error!')
    exit(1)

# See EIP-155 for the list of other well-known Net IDs
networks = {
    1: {'name': 'Mainnet', 'engine': 'PoW'},
    5: {'name': 'Goerli', 'engine': 'PoA'},
    1337: {'name': 'E2E', 'engine': 'PoA'}
}

network_id = w3.eth.chainId
if network_id in networks.keys():
    logging.info(f"Connected to {networks[network_id]['name']} network ({networks[network_id]['engine']} engine)")
    if networks[network_id]['engine'] == 'PoA':
        logging.info("Injecting PoA compatibility middleware")
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

if dry_run:
    logging.info('MEMBER_PRIV_KEY not provided, running in read-only (DRY RUN) mode')
else:
    logging.info('MEMBER_PRIV_KEY provided, running in transactable (PRODUCTION) mode')
    account = w3.eth.account.from_key(member_privkey)
    logging.info(f'Member account: {account.address}')

# Get Pool contract
with open(pool_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
pool = w3.eth.contract(abi=abi['abi'], address=pool_address)  # contract object

# Get Oracle contract
oracle_address = pool.functions.getOracle().call()  # oracle contract

with open(oracle_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
oracle = w3.eth.contract(abi=abi['abi'], address=oracle_address)

# Get Registry contract
registry_address = pool.functions.getOperators().call()

with open(registry_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
registry = w3.eth.contract(abi=abi['abi'], address=registry_address)

# Get Beacon specs from contract
beacon_spec = oracle.functions.beaconSpec().call()
epochs_per_frame = beacon_spec[0]
slots_per_epoch = beacon_spec[1]
seconds_per_slot = beacon_spec[2]
genesis_time = beacon_spec[3]

beacon = get_beacon(beacon_provider, slots_per_epoch)  # >>lighthouse<< / prism implementation of ETH 2.0

if run_as_daemon:
    logging.info('DAEMON=1 Running in daemon mode (in endless loop).')
else:
    logging.info('DAEMON=0 Running in single iteration mode (will exit after reporting).')

logging.info(f'ETH1_NODE={eth1_provider}')
logging.info(f'BEACON_NODE={beacon_provider} ({beacon.__class__.__name__} API)')
logging.info(f'SLEEP={await_time_in_sec} s (pause between iterations in DAEMON mode)')
logging.info(f'GAS_LIMIT={GAS_LIMIT} gas units')
logging.info(f'POOL_CONTRACT={pool_address}')
logging.info(f'Oracle contract address: {oracle_address} (auto-discovered)')
logging.info(f'Registry contract address: {registry_address} (auto-discovered)')
logging.info(f'Seconds per slot: {seconds_per_slot} (auto-discovered)')
logging.info(f'Slots per epoch: {slots_per_epoch} (auto-discovered)')
logging.info(f'Epochs per frame: {epochs_per_frame} (auto-discovered)')
logging.info(f'Genesis time: {genesis_time} (auto-discovered)')


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
    delta_seconds = current.timestamp - previous.timestamp
    logging.info(f'Time delta: {datetime.timedelta(seconds = delta_seconds)} or {delta_seconds} s')
    logging.info(f'depositedValidators before:{previous.depositedValidators} after:{current.depositedValidators} change:{current.depositedValidators - previous.depositedValidators}')
    if current.beaconValidators < previous.beaconValidators:
        logging.warning('The number of beacon validators unexpectedly decreased!')
    logging.info(f'beaconValidators before:{previous.beaconValidators} after:{current.beaconValidators} change:{current.beaconValidators - previous.beaconValidators}')
    logging.info(f'transientValidators before:{previous.getTransientValidators()} after:{current.getTransientValidators()} change:{current.getTransientValidators() - previous.getTransientValidators()}')
    logging.info(f'beaconBalance before:{previous.beaconBalance} after:{current.beaconBalance} change:{current.beaconBalance - previous.beaconBalance}')
    logging.info(f'bufferedBalance before:{previous.bufferedBalance} after:{current.bufferedBalance} change:{current.bufferedBalance - previous.bufferedBalance}')
    logging.info(f'transientBalance before:{previous.getTransientBalance()} after:{current.getTransientBalance()} change:{current.getTransientBalance() - previous.getTransientBalance()}')
    logging.info(f'totalPooledEther before:{previous.getTotalPooledEther()} after:{current.getTotalPooledEther()} ')
    total_pooled_eth_increase = current.getTotalPooledEther() - previous.getTotalPooledEther()
    if total_pooled_eth_increase > 0:
        logging.info(f'totalPooledEther will increase by {total_pooled_eth_increase} wei or {total_pooled_eth_increase/1e18} ETH')
        # APR calculation
        days = delta_seconds / 60 / 60 / 24
        daily_interest_rate = total_pooled_eth_increase / previous.getTotalPooledEther() / days
        apr = daily_interest_rate * 365
        logging.info(f'Increase since last report: {total_pooled_eth_increase / previous.getTotalPooledEther() * 100:.4f} %')
        logging.info(f'Expected APR: {apr * 100:.4f} %')

    elif total_pooled_eth_increase < 0:
        logging.warning(f'totalPooledEther will decrease by {-total_pooled_eth_increase} wei or {-total_pooled_eth_increase/1e18} ETH')
        logging.warning('Validators were either slashed or suffered penalties!')
    else:
        logging.info('totalPooledEther will stay intact. This won\'t have any economical impact on the pool.')


def build_report_beacon_tx(epoch, balance, validators):  # hash tx
    return oracle.functions.reportBeacon(
        epoch, balance, validators
    ).buildTransaction({'from': account.address, 'gas': GAS_LIMIT})


def sign_and_send_tx(tx):
    logging.info('Preparing TX... CTRL-C to abort')
    time.sleep(3)  # To be able to Ctrl + C
    tx['nonce'] = w3.eth.getTransactionCount(
        account.address
    )  # Get correct transaction nonce for sender from the node
    signed = w3.eth.account.signTransaction(tx, account.privateKey)
    logging.info(f'TX hash: {signed.hash.hex()} ... CTRL-C to abort')
    time.sleep(3)
    logging.info('Sending TX... CTRL-C to abort')
    time.sleep(3)
    tx_hash = w3.eth.sendRawTransaction(signed.rawTransaction)
    logging.info('TX has been sent. Waiting for receipt...')
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    if tx_receipt.status == 1:
        logging.info('TX successful')
    else:
        logging.warning('TX reverted')
        logging.warning(tx_receipt)


def prompt(prompt_message, prompt_end):
    print(prompt_message, end='')
    while True:
        choice = input().lower()
        if choice == 'y':
            return True
        elif choice == 'n':
            return False
        else:
            print('Please respond with [y or n]: ', end=prompt_end)
            continue


def get_previous_metrics():
    """Since the contract lacks a method that returns the time of last report and the reported numbers
    we are using web3.py filtering to fetch it from the contract events."""
    logging.info('Getting previously reported numbers (will be fetched from events)...')
    SECONDS_PER_ETH1_BLOCK = 14
    latest_block = w3.eth.getBlock('latest')
    # Calculate earliest block to limit scanning depth
    from_block = int((latest_block['timestamp']-genesis_time)/SECONDS_PER_ETH1_BLOCK)
    events = oracle.events.Completed.getLogs(fromBlock=from_block, toBlock='latest')
    if events:
        result = PoolMetrics()
        event = events[-1]
        result.epoch = event['args']['epochId']
        result.beaconBalance = event['args']['beaconBalance']
        result.beaconValidators = event['args']['beaconValidators']
        block = w3.eth.getBlock(event['blockHash'])
        result.timestamp = block['timestamp']
        result.bufferedBalance = pool.functions.getBufferedEther().call(block_identifier=block.number)
        deposited_validators, beaconValidators, beaconBalance = pool.functions.getBeaconStat().call(block_identifier=block.number)
        assert beaconValidators == result.beaconValidators
        assert beaconBalance == result.beaconBalance
        result.depositedValidators = deposited_validators
        assert result.getTotalPooledEther() == pool.functions.getTotalPooledEther().call(block_identifier=block.number)
        return result
    else:
        logging.info('No events on the contract. It\'s ok if it\'s the first run.')
        return False


def get_current_metrics():
    result = PoolMetrics()
    # Get the the epoch that is both finalized and reportable
    current_frame = oracle.functions.getCurrentFrame().call()
    potentially_reportable_epoch = current_frame[0]
    logging.info(f'Potentially reportable epoch: {potentially_reportable_epoch} (from ETH1 contract)')
    finalized_epoch_beacon = beacon.get_finalized_epoch()
    logging.info(f'Last finalized epoch: {finalized_epoch_beacon} (from Beacon)')
    result.epoch = min(potentially_reportable_epoch, (finalized_epoch_beacon // epochs_per_frame) * epochs_per_frame)
    slot = result.epoch * slots_per_epoch
    logging.info(f'Reportable state: epoch:{result.epoch} slot:{slot}')

    validators_keys = get_validators_keys(registry)
    logging.info(f'Total validator keys in registry: {len(validators_keys)}')

    result.timestamp = w3.eth.getBlock('latest')['timestamp']
    result.beaconBalance, result.beaconValidators = beacon.get_balances(slot, validators_keys)
    result.depositedValidators = pool.functions.getBeaconStat().call()[0]
    result.bufferedBalance = pool.functions.getBufferedEther().call()
    logging.info(f'Lido validators\' sum. balance on Beacon: {result.beaconBalance} wei or {result.beaconBalance/1e18} ETH')
    logging.info(f'Lido validators visible on Beacon: {result.beaconValidators}')
    return result


logging.info('Starting the main loop')
while True:
    # Get previously reported data
    prev_metrics = get_previous_metrics()
    if prev_metrics:
        logging.info(f'Previously reported epoch: {prev_metrics.epoch}')
        logging.info(f'Previously reported beaconBalance: {prev_metrics.beaconBalance} wei or {prev_metrics.beaconBalance/1e18} ETH')
        logging.info(f'Previously reported bufferedBalance: {prev_metrics.bufferedBalance} wei or {prev_metrics.bufferedBalance/1e18} ETH')
        logging.info(f'Previous validator metrics: depositedValidators:{prev_metrics.depositedValidators}')
        logging.info(f'Previous validator metrics: transientValidators:{prev_metrics.getTransientValidators()}')
        logging.info(f'Previous validator metrics: beaconValidators:{prev_metrics.beaconValidators}')
        logging.info(f'Timestamp of previous report: {datetime.datetime.fromtimestamp(prev_metrics.timestamp)} or {prev_metrics.timestamp}')

    current_metrics = get_current_metrics()

    if prev_metrics and current_metrics.epoch <= prev_metrics.epoch:
        logging.info(f'Currently reportable epoch {current_metrics.epoch} has already been reported. Skipping it.')
    else:
        if prev_metrics:
            compare_pool_metrics(prev_metrics, current_metrics)
        logging.info(f'Tx call data: oracle.reportBeacon({current_metrics.epoch}, {current_metrics.beaconBalance}, {current_metrics.beaconValidators})')
        if not dry_run:
            try:
                tx = build_report_beacon_tx(current_metrics.epoch, current_metrics.beaconBalance, current_metrics.beaconValidators)
                # Create the tx and execute it locally to check validity
                w3.eth.call(tx)
                logging.info('Calling tx locally succeeded.')
                if run_as_daemon:
                    sign_and_send_tx(tx)
                else:
                    print(f'Tx data: {tx.__repr__()}')
                    if prompt('Should we send this TX? [y/n]: ', ''):
                        sign_and_send_tx(tx)

            except SolidityError as sl:
                str_sl = str(sl)
                if "EPOCH_IS_TOO_OLD" in str_sl:
                    logging.info('Calling tx locally reverted "EPOCH_IS_TOO_OLD"')
                elif "ALREADY_SUBMITTED" in str_sl:
                    logging.info('Calling tx locally reverted "ALREADY_SUBMITTED"')
                elif "EPOCH_HAS_NOT_YET_BEGUN" in str_sl:
                    logging.info('Calling tx locally reverted "EPOCH_HAS_NOT_YET_BEGUN"')
                elif "MEMBER_NOT_FOUND" in str_sl:
                    logging.warning('Calling tx locally reverted "MEMBER_NOT_FOUND". Maybe you are using the address that is not in the members list?')
                elif "REPORTED_MORE_DEPOSITED" in str_sl:
                    logging.warning('Calling tx locally reverted "REPORTED_MORE_DEPOSITED". Something wrong with calculated balances on the beacon or the validators list')
                elif "REPORTED_LESS_VALIDATORS" in str_sl:
                    logging.warning('Calling tx locally reverted "REPORTED_LESS_VALIDATORS". Oracle can\'t report less validators than seen on the Beacon before.')
                else:
                    logging.error(f'Calling tx locally failed: {str_sl}')

            except Exception as exc:
                logging.exception(f'Unexpected exception. {type(exc)}')

        else:
            logging.info('The tx hasn\'t been actually sent to the oracle contract! We are in DRY RUN mode')
            logging.info('Provide MEMBER_PRIV_KEY to be able to transact')

    if not run_as_daemon:
        logging.info('We are in single-iteration mode, so exiting. Set DAEMON=1 env to run in the loop.')
        break

    logging.info(f'We are in DAEMON mode. Sleep {await_time_in_sec} s and continue')
    time.sleep(await_time_in_sec)
