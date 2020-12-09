# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import binascii
import json
import logging
import os
import time
import traceback

from web3 import Web3, WebsocketProvider, HTTPProvider

from beacon import get_beacon
from contracts import get_validators_keys

logging.basicConfig(
    level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)

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

eth1_provider = os.environ['ETH1_NODE']
beacon_provider = os.environ['BEACON_NODE']
pool_address = os.environ['POOL_CONTRACT']
if not Web3.isChecksumAddress(pool_address):
    pool_address = Web3.toChecksumAddress(pool_address)
oracle_abi_path = os.path.join(ARTIFACTS_DIR, ORACLE_ARTIFACT_FILE)
pool_abi_path = os.path.join(ARTIFACTS_DIR, POOL_ARTIFACT_FILE)
registry_abi_path = os.path.join(ARTIFACTS_DIR, REGISTRY_ARTIFACT_FILE)
member_privkey = os.getenv('MEMBER_PRIV_KEY')
await_time_in_sec = int(os.getenv('SLEEP', 60))

run_as_daemon = int(os.getenv('DAEMON', 0))

dry_run = member_privkey is None

GAS_LIMIT = int(os.getenv('GAS_LIMIT', 1_500_000))

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
    1: {'name': 'Mainnet', 'engine':'PoW'},
    5: {'name': 'Goerli', 'engine':'PoA'},
    1337: {'name': 'E2E', 'engine':'PoA'}
}

network_id = w3.eth.chainId
if network_id in networks.keys():
    logging.info(f"Connected to {networks[network_id]['name']} network ({networks[network_id]['engine']} engine)")
    if networks[network_id]['engine'] == 'PoA':
        logging.info(f"Injecting PoA compatibility middleware")
        from web3.middleware import geth_poa_middleware
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)

if dry_run:
    logging.info('MEMBER_PRIV_KEY not provided, running in read-only (DRY RUN) mode')
else:
    logging.info('MEMBER_PRIV_KEY provided, running in transactable (PRODUCTION) mode')
    account = w3.eth.account.privateKeyToAccount(member_privkey)
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
logging.info(f'SLEEP={await_time_in_sec} s')
logging.info(f'GAS_LIMIT={GAS_LIMIT} gas units')
logging.info(f'POOL_CONTRACT={pool_address}')
logging.info(f'Oracle contract address: {oracle_address} (auto-discovered)')
logging.info(f'Registry contract address: {registry_address} (auto-discovered)')
logging.info(f'Seconds per slot: {seconds_per_slot} (auto-discovered)')
logging.info(f'Slots per epoch: {slots_per_epoch} (auto-discovered)')
logging.info(f'Epochs per frame: {epochs_per_frame} (auto-discovered)')
logging.info(f'Genesis time: {genesis_time} (auto-discovered)')


def build_report_beacon_tx(reportable_epoch, sum_balance, validators_on_beacon):  # hash tx
    return oracle.functions.reportBeacon(
        reportable_epoch, sum_balance, validators_on_beacon
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
    logging.info(f'Sending TX... CTRL-C to abort')
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


logging.info('Starting the main loop')
while True:
    # Get the the epoch that is both finalized and reportable
    current_frame = oracle.functions.getCurrentFrame().call()
    potentially_reportable_epoch = current_frame[0]
    logging.info(f'Potentially reportable epoch: {potentially_reportable_epoch} (from ETH1 contract)')
    finalized_epoch_beacon = beacon.get_finalized_epoch()
    logging.info(f'Last finalized epoch: {finalized_epoch_beacon} (from Beacon)')
    reportable_epoch = min(potentially_reportable_epoch, (finalized_epoch_beacon // epochs_per_frame) * epochs_per_frame)
    reportable_slot = reportable_epoch * slots_per_epoch
    logging.info(f'Reportable state: epoch:{reportable_epoch} slot:{reportable_slot}')

    validators_keys = get_validators_keys(registry)
    logging.info(f'Total validator keys in registry: {len(validators_keys)}')
    sum_balance, validators_on_beacon = beacon.get_balances(reportable_slot, validators_keys)

    logging.info(f'Total balance on Beacon: {sum_balance} wei')
    logging.info(f'Lido validators on Beacon: {validators_on_beacon}')
    logging.info(f'Tx call data: oracle.reportBeacon({reportable_epoch}, {sum_balance}, {validators_on_beacon})')
    if not dry_run:
        try:
            tx = build_report_beacon_tx(reportable_epoch, sum_balance, validators_on_beacon)
            # Create the tx and execute it locally to check validity
            w3.eth.call(tx)
            logging.info('Calling tx locally is succeeded.')
            if run_as_daemon:
                sign_and_send_tx(tx)
            else:
                print(f'Tx data: {tx.__repr__()}')
                if prompt('Should we sent this TX? [y/n]: ', ''):
                    sign_and_send_tx(tx)
        except Exception as exc:
            if isinstance(exc, ValueError) and 'execution reverted: EPOCH_IS_TOO_OLD' in str(exc):
                # e.g. {
                #   'code': 3,
                #   'message':
                #   'execution reverted: EPOCH_IS_TOO_OLD',
                #   'data': '0x08c379a00000000000000000000000000000000000000000000000000000000000000020000000000000000000000000000000000000000000000000000000000000001045504f43485f49535f544f4f5f4f4c4400000000000000000000000000000000'
                # }
                logging.warning(f'execution reverted: EPOCH_IS_TOO_OLD')
            else:
                logging.exception(f'Unexpected exception. {type(exc)}')
    else:
        logging.info('The tx hasn\'t been actually sent to the oracle contract! We are in DRY RUN mode')
        logging.info('Provide MEMBER_PRIV_KEY to be able to transact')

    if not run_as_daemon:
        logging.info('We are in single-iteration mode, so exiting. Set DAEMON=1 env to run in the loop.')
        break

    logging.info(f'We are in DAEMON mode. Sleep {await_time_in_sec} s and continue')
    time.sleep(await_time_in_sec)
