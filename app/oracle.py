# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import json
import logging
import os
import datetime
import time

from prometheus_client import start_http_server
from web3 import Web3, WebsocketProvider, HTTPProvider
from web3.exceptions import SolidityError, CannotHandleRequest

from beacon import get_beacon
from contracts import get_total_supply
from log import init_log
from metrics import compare_pool_metrics, get_current_metrics, get_previous_metrics
from prometheus_metrics import metrics_exporter_state
from state_proof import encode_proof_data

init_log(stdout_level=os.environ.get('LOG_LEVEL_STDOUT', 'INFO'))
logger = logging.getLogger()

meta_envs = ['VERSION', 'COMMIT_MESSAGE', 'COMMIT_HASH', 'COMMIT_DATETIME', 'BUILD_DATETIME', 'TAGS', 'BRANCH']

for env in meta_envs:
    value = 'Not set'
    if env in os.environ and os.environ[env] != '':
        value = os.environ[env]
    logging.info(f'{env.lower()}: {value}')

envs = [
    'WEB3_PROVIDER_URI',
    'BEACON_NODE',
    'POOL_CONTRACT',
    'STETH_CURVE_POOL_CONTRACT',
    'STETH_PRICE_ORACLE_CONTRACT',
]
if os.getenv('FORCE'):
    logging.error('The flag "FORCE" is obsolete in favour of '
        '"FORCE_DO_NOT_USE_IN_PRODUCTION", '
        'please NEVER use it in production')
    exit(1)

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
STETH_CURVE_POOL_FILE = 'StableSwapPool.json'
STETH_PRICE_ORACLE_FILE = 'StableSwapStateOracle.json'

DEFAULT_SLEEP = 60
DEFAULT_COUNTDOWN_SLEEP = 10
DEFAULT_GAS_LIMIT = 1_500_000

prometheus_metrics_port = int(os.getenv('PROMETHEUS_METRICS_PORT', 8000))

steth_price_oracle_block_number_shift = int(os.getenv('STETH_PRICE_ORACLE_BLOCK_NUMBER_SHIFT', 15))
eth1_provider = os.environ['WEB3_PROVIDER_URI']
beacon_provider = os.environ['BEACON_NODE']

pool_address = os.environ['POOL_CONTRACT']
if not Web3.isChecksumAddress(pool_address):
    pool_address = Web3.toChecksumAddress(pool_address)

steth_curve_pool_address = os.environ['STETH_CURVE_POOL_CONTRACT']
if not Web3.isChecksumAddress(steth_curve_pool_address):
    steth_curve_pool_address = Web3.toChecksumAddress(steth_curve_pool_address)

steth_price_oracle_address = os.environ['STETH_PRICE_ORACLE_CONTRACT']
if not Web3.isChecksumAddress(steth_price_oracle_address):
    steth_price_oracle_address = Web3.toChecksumAddress(steth_price_oracle_address)

oracle_abi_path = os.path.join(ARTIFACTS_DIR, ORACLE_ARTIFACT_FILE)
pool_abi_path = os.path.join(ARTIFACTS_DIR, POOL_ARTIFACT_FILE)
registry_abi_path = os.path.join(ARTIFACTS_DIR, REGISTRY_ARTIFACT_FILE)
steth_curve_pool_abi_path = os.path.join(ARTIFACTS_DIR, STETH_CURVE_POOL_FILE)
steth_price_oracle_abi_path = os.path.join(ARTIFACTS_DIR, STETH_PRICE_ORACLE_FILE)
member_privkey = os.getenv('MEMBER_PRIV_KEY')
SLEEP = int(os.getenv('SLEEP', DEFAULT_SLEEP))
COUNTDOWN_SLEEP = int(os.getenv('COUNTDOWN_SLEEP', DEFAULT_COUNTDOWN_SLEEP))

run_as_daemon = int(os.getenv('DAEMON', 0))
force = int(os.getenv('FORCE_DO_NOT_USE_IN_PRODUCTION', 0))

dry_run = member_privkey is None

GAS_LIMIT = int(os.getenv('GAS_LIMIT', DEFAULT_GAS_LIMIT))

ORACLE_FROM_BLOCK = int(os.getenv('ORACLE_FROM_BLOCK', 0))

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
    1337: {'name': 'E2E', 'engine': 'PoA'},
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
logger.info(f'{oracle_address=}')

with open(oracle_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
oracle = w3.eth.contract(abi=abi['abi'], address=oracle_address)

# Get Registry contract
registry_address = pool.functions.getOperators().call()
logger.info(f'{registry_address=}')

with open(registry_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
registry = w3.eth.contract(abi=abi['abi'], address=registry_address)

# Get StETHCurvePool contract
with open(steth_curve_pool_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
steth_curve_pool = w3.eth.contract(abi=abi, address=steth_curve_pool_address)

# Get StETHPriceOracle contract
with open(steth_price_oracle_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
steth_price_oracle = w3.eth.contract(abi=abi, address=steth_price_oracle_address)

# Get Beacon specs from contract
beacon_spec = oracle.functions.getBeaconSpec().call()
epochs_per_frame = beacon_spec[0]
slots_per_epoch = beacon_spec[1]
seconds_per_slot = beacon_spec[2]
genesis_time = beacon_spec[3]

beacon = get_beacon(beacon_provider, slots_per_epoch)  # >>lighthouse<< / prism implementation of ETH 2.0

if run_as_daemon:
    logging.info('DAEMON=1 Running in daemon mode (in endless loop).')
else:
    logging.info('DAEMON=0 Running in single iteration mode (will exit after reporting).')

if force:
    logging.info('FORCE_DO_NOT_USE_IN_PRODUCTION=1 Running in enforced mode.')
    logging.warning("In enforced mode TX gets always sent even if it looks suspicious. NEVER use it in production!")

logging.info(f'WEB3_PROVIDER_URI={eth1_provider}')
logging.info(f'BEACON_NODE={beacon_provider} ({beacon.__class__.__name__} API)')
logging.info(f'SLEEP={SLEEP} s (pause between iterations in DAEMON mode)')
logging.info(f'GAS_LIMIT={GAS_LIMIT} gas units')
logging.info(f'POOL_CONTRACT={pool_address}')
logging.info(f'STETH_CURVE_POOL_CONTRACT={steth_curve_pool_address}')
logging.info(f'STETH_PRICE_ORACLE_CONTRACT={steth_price_oracle_address}')
logging.info(f'STETH_PRICE_ORACLE_BLOCK_NUMBER_SHIFT={steth_price_oracle_block_number_shift}')
logging.info(f'Oracle contract address: {oracle_address} (auto-discovered)')
logging.info(f'Registry contract address: {registry_address} (auto-discovered)')
logging.info(f'Seconds per slot: {seconds_per_slot} (auto-discovered)')
logging.info(f'Slots per epoch: {slots_per_epoch} (auto-discovered)')
logging.info(f'Epochs per frame: {epochs_per_frame} (auto-discovered)')
logging.info(f'Genesis time: {genesis_time} (auto-discovered)')


# fixme
# @metrics_exporter_state.totalSupply.time()
# def process_get_total_supply():
#     return get_total_supply(pool)
# print(f'{get_total_supply(oracle)=}')

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
    signed = w3.eth.account.sign_transaction(tx, account.key)
    logging.info(f'TX hash: {signed.hash.hex()} ... CTRL-C to abort')
    time.sleep(3)
    logging.info('Sending TX... CTRL-C to abort')
    time.sleep(3)
    tx_hash = w3.eth.sendRawTransaction(signed.rawTransaction)
    logging.info('TX has been sent. Waiting for receipt...')
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    if tx_receipt.status == 1:
        logging.info('TX successful')
        metrics_exporter_state.txSuccess.observe(1)
    else:
        logging.warning('TX reverted')
        logging.warning(tx_receipt)
        metrics_exporter_state.txRevert.observe(1)


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


def main():
    logger.info(f'start prometheus metrics server on the port: {prometheus_metrics_port}')
    start_http_server(prometheus_metrics_port)

    logging.info('Starting the main loop')
    while True:
        try:
            run_once()
            sleep()
        except StopIteration:
            break
        except CannotHandleRequest as exc:
            if 'Could not discover provider while making request: method:eth_chainId' in str(exc):
                logger.exception("handle 'Could not discover provider' problem")
                time.sleep(1)
                continue
            else:
                raise


def run_once():
    update_beacon_data()
    update_steth_price_oracle_data()

    if not run_as_daemon:
        logging.info('We are in single-iteration mode, so exiting. Set DAEMON=1 env to run in the loop.')
        raise StopIteration()

    logging.info(f'We are in DAEMON mode. Sleep {SLEEP} s and continue')


def update_beacon_data():
    # Get previously reported data
    prev_metrics = get_previous_metrics(w3, pool, oracle, beacon_spec, ORACLE_FROM_BLOCK)
    metrics_exporter_state.set_prev_pool_metrics(prev_metrics)
    if prev_metrics:
        logging.info(f'Previously reported epoch: {prev_metrics.epoch}')
        logging.info(f'Previously reported beaconBalance: {prev_metrics.beaconBalance} wei or {prev_metrics.beaconBalance/1e18} ETH')
        logging.info(f'Previously reported bufferedBalance: {prev_metrics.bufferedBalance} wei or {prev_metrics.bufferedBalance/1e18} ETH')
        logging.info(f'Previous validator metrics: depositedValidators:{prev_metrics.depositedValidators}')
        logging.info(f'Previous validator metrics: transientValidators:{prev_metrics.getTransientValidators()}')
        logging.info(f'Previous validator metrics: beaconValidators:{prev_metrics.beaconValidators}')
        logging.info(f'Timestamp of previous report: {datetime.datetime.fromtimestamp(prev_metrics.timestamp)} or {prev_metrics.timestamp}')

    # Get minimal metrics that are available without polling
    current_metrics = get_current_metrics(w3, beacon, pool, oracle, registry, beacon_spec)
    metrics_exporter_state.set_current_pool_metrics(current_metrics)
    if current_metrics.epoch <= prev_metrics.epoch:  # commit happens once per day
        logging.info(f'Currently reportable epoch {current_metrics.epoch} has already been reported. Skipping it.')
        return


    # Get full metrics using polling (get keys from reggistry, get balances from beacon)
    current_metrics = get_current_metrics(w3, beacon, pool, oracle, registry, beacon_spec, partial_metrics=current_metrics)
    metrics_exporter_state.set_current_pool_metrics(current_metrics)
    warnings = compare_pool_metrics(prev_metrics, current_metrics)

    logging.info(f'Tx call data: oracle.reportBeacon({current_metrics.epoch}, {current_metrics.beaconBalance}, {current_metrics.beaconValidators})')
    if not dry_run:
        try:
            metrics_exporter_state.reportableFrame.set(True)
            tx = build_report_beacon_tx(current_metrics.epoch, current_metrics.beaconBalance, current_metrics.beaconValidators)
            # Create the tx and execute it locally to check validity
            w3.eth.call(tx)
            logging.info('Calling tx locally succeeded.')
            if run_as_daemon:
                if warnings:
                    if force:
                        sign_and_send_tx(tx)
                    else:
                        logging.warning('Cannot report suspicious data in DAEMON mode for safety reasons.')
                        logging.warning('You can submit it interactively (with DAEMON=0) and interactive [y/n] prompt.')
                        logging.warning("In DAEMON mode it's possible with enforcement flag (FORCE_DO_NOT_USE_IN_PRODUCTION=1). Never use it in production.")
                else:
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


def update_steth_price_oracle_data():
    logging.info('Check StETH Price Oracle state')
    try:
        block_number = w3.eth.block_number - steth_price_oracle_block_number_shift


        oracle_price = steth_price_oracle.functions.stethPrice().call()
        pool_price = steth_curve_pool.functions.get_dy(1, 0, 10 ** 18).call(block_identifier=block_number)
        percentage_diff = 100 * abs(1 - oracle_price / pool_price)
        logging.info(
            f'StETH stats: (pool price - {pool_price / 1e18:.6f}, oracle price - {oracle_price / 1e18:.6f}, difference - {percentage_diff:.2f}%)'
        )

        pool_eth_balance = steth_curve_pool.functions.balances(0).call()
        pool_steth_balance = steth_curve_pool.functions.balances(1).call()
        
        metrics_exporter_state.set_steth_pool_metrics(oracle_price, pool_price, pool_eth_balance, pool_steth_balance)

        proof_params = steth_price_oracle.functions.getProofParams().call()

        # proof_params[-1] contains priceUpdateThreshold value in basis points: 10000 BP equal to 100%, 100 BP to 1%.
        price_update_threshold = proof_params[-1] / 100
        is_state_actual = percentage_diff < price_update_threshold

        if is_state_actual:
            logging.info(f'StETH Price Oracle state valid (prices difference < {price_update_threshold:.2f}%). No update required.')
            return

        if dry_run:
            logging.warning("Running in dry run mode. New state will not be submitted.")
            return

        logging.info(f'StETH Price Oracle state outdated (prices difference >= {price_update_threshold:.2f}%). Submiting new one...')

        header_blob, proofs_blob = encode_proof_data(provider, block_number, proof_params)

        tx = steth_price_oracle.functions.submitState(header_blob, proofs_blob).buildTransaction(
            {'gas': 2_000_000}
        )

        w3.eth.call(tx)
        sign_and_send_tx(tx)
    except SolidityError as sl:
        logging.error(f'Tx call failed : {sl}')


def sleep():
    # sleep and countdown
    awake_at = time.time() + SLEEP
    while time.time() < awake_at:
        time.sleep(COUNTDOWN_SLEEP)
        countdown = awake_at - time.time()
        if countdown < 0:
            break
        metrics_exporter_state.reportableFrame.set(False)
        metrics_exporter_state.daemonCountDown.set(countdown)
        blocknumber = w3.eth.getBlock('latest')['number']
        metrics_exporter_state.nowEthV1BlockNumber.set(blocknumber)
        finalized_epoch_beacon = beacon.get_finalized_epoch()
        metrics_exporter_state.finalizedEpoch.set(finalized_epoch_beacon)

        logger.info(f'{awake_at=} {countdown=} {blocknumber=} {finalized_epoch_beacon=}')


if __name__ == '__main__':
    main()
