import sys
import traceback
import binascii
import json
import logging
import os
import time
import random

from web3 import Web3, WebsocketProvider, HTTPProvider
from web3.exceptions import (
    SolidityError
)

from beacon import get_beacon
from contracts import get_validators_keys

logging.basicConfig(
    level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s', datefmt='%m-%d %H:%M:%S'
)

envs = [
    'ETH1_NODE',
    'ETH2_NODE',
    'LIDO_CONTRACT',
    'MANAGER_PRIV_KEY',
]
missing = []
for env in envs:
    if env not in os.environ or os.environ[env] == '':
        missing.append(env)
        logging.error('Variable %s is missing', env)

if missing:
    exit(1)

ARTIFACTS_DIR = './assets'
ORACLE_ARTIFACT_FILE = 'LidoOracle.json'
POOL_ARTIFACT_FILE = 'Lido.json'
REGISTRY_ARTIFACT_FILE = 'NodeOperatorsRegistry.json'

eth1_provider = os.environ['ETH1_NODE']
eth2_provider = os.environ['ETH2_NODE']
pool_address = os.environ['LIDO_CONTRACT']
if not Web3.isChecksumAddress(pool_address):
    pool_address = Web3.toChecksumAddress(pool_address)
oracle_abi_path = os.path.join(ARTIFACTS_DIR, ORACLE_ARTIFACT_FILE)
pool_abi_path = os.path.join(ARTIFACTS_DIR, POOL_ARTIFACT_FILE)
registry_abi_path = os.path.join(ARTIFACTS_DIR, REGISTRY_ARTIFACT_FILE)
manager_privkey = os.environ['MANAGER_PRIV_KEY']

GAS_LIMIT = int(os.getenv('GAS_LIMIT', 1000000))

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

w3.eth.defaultAccount = w3.eth.account.privateKeyToAccount(manager_privkey)

# Get Pool contract
with open(pool_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
pool = w3.eth.contract(abi=abi['abi'], address=pool_address)

# Get Oracle contract
oracle_address = pool.functions.getOracle().call({'from': w3.eth.defaultAccount.address})

with open(oracle_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
oracle = w3.eth.contract(abi=abi['abi'], address=oracle_address)

# Get Registry contract
registry_address = pool.functions.getOperators().call({'from': w3.eth.defaultAccount.address})

with open(registry_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
registry = w3.eth.contract(abi=abi['abi'], address=registry_address)

# Get Beacon specs from contract
beacon_spec = oracle.functions.beaconSpec().call({'from': w3.eth.defaultAccount.address})
slots_per_epoch = beacon_spec[1]
seconds_per_slot = beacon_spec[2]

beacon = get_beacon(eth2_provider, slots_per_epoch)

isDaemon = '--daemon' in sys.argv
shouldSubmitTx = '--submit-tx' in sys.argv

if not shouldSubmitTx:
    logging.info('Running in a DRY RUN mode! Pass the --submit-tx flag to perform actual reporting.')

if isDaemon:
    logging.info('=====The oracle daemon is started!=====')
else:
    logging.info('Pass the --daemon flag to run as a daemon.')

oracle_sleep_duration = seconds_per_slot * slots_per_epoch

logging.info('============ CONFIGURATION ============')
logging.info(f'ETH1 Node: {eth1_provider}')
logging.info(f'ETH2 Node: {eth2_provider}')
logging.info('Connecting to %s', beacon.__class__.__name__)
logging.info(f'Pool contract address: {pool_address}')
logging.info(f'Oracle contract address: {oracle_address}')
logging.info(f'Registry contract address: {registry_address}')
logging.info(f'Manager account: {w3.eth.defaultAccount.address}')
logging.info(f'Seconds per slot: {seconds_per_slot}')
logging.info(f'Slots per epoch: {slots_per_epoch}')
logging.info(f'Oracle sleep duration after each step: {oracle_sleep_duration} secs')
logging.info('=======================================')

def build_report_beacon_tx(reportable_epoch, sum_balance, validators_on_beacon):
    return oracle.functions.reportBeacon(
        reportable_epoch, sum_balance, validators_on_beacon 
    ).buildTransaction({'from': w3.eth.defaultAccount.address, 'gas': GAS_LIMIT})

def sign_and_send_tx(tx):
    logging.info('Prepearing to send a tx...')
    
    if not isDaemon:
        time.sleep(5) # To be able to Ctrl + C

    tx['nonce'] = w3.eth.getTransactionCount(
        w3.eth.defaultAccount.address
    )  # Get correct transaction nonce for sender from the node
    signed = w3.eth.account.signTransaction(tx, w3.eth.defaultAccount.privateKey)
    
    tx_hash = w3.eth.sendRawTransaction(signed.rawTransaction)
    logging.info('Transaction in progress...')
    
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)

    str_tx_hash = '0x' + binascii.hexlify(tx_receipt.transactionHash).decode()
    logging.info(f'Transaction hash: {str_tx_hash}')
    
    if tx_receipt.status == 1:
        logging.info('Transaction successful')
        logging.info('Balances pushed!')
    else:
        logging.warning('Transaction reverted')
        logging.warning(tx_receipt)

while True:
    try:
        current_frame = oracle.functions.getCurrentFrame().call({'from': w3.eth.defaultAccount.address})
        reportable_epoch = current_frame[0]
        
        finalized_epoch = beacon.get_finalized_epoch()
        
        if reportable_epoch > finalized_epoch:
            logging.info(f'Next reportable epoch ({reportable_epoch}) is greater than Beacon chain finalized epoch ({finalized_epoch}), skipping...')
            continue
        
        logging.info('=======================================')
        logging.info(f'Reportable epoch: {reportable_epoch}')
        logging.info(f'Beacon finalized epoch: {finalized_epoch}')
        
        slot = reportable_epoch * slots_per_epoch
        logging.info(f'Beacon finalized slot: {slot}')
        
        validators_keys = get_validators_keys(registry, w3)
        logging.info(f'Total validator keys in registry: {len(validators_keys)}')
        
        sum_balance, validators_on_beacon = beacon.get_balances(slot, validators_keys)
        
        logging.info(f'ReportBeacon transaction arguments:')
        logging.info(f'Reportable epoch: {reportable_epoch}')
        logging.info(f'Sum balance in wei: {sum_balance}')
        logging.info(f'Validators number on Beacon chain: {validators_on_beacon}')

        if isDaemon:
            # To randomize tx submission moment in case of simultaneous
            # launch of several oracles
            random_wait_in_sec = random.randrange(1, 120)
            time.sleep(random_wait_in_sec)

        tx = build_report_beacon_tx(reportable_epoch, sum_balance, validators_on_beacon)
        
        w3.eth.call(tx)
        
        logging.info('Calling tx locally is succeeded')

        if shouldSubmitTx:
            sign_and_send_tx(tx)
        else:
            logging.info('DRY RUN! The tx hasnt been sent to the oracle contract!')
    except SolidityError as sl:
        str_sl = str(sl)
        if "EPOCH_IS_TOO_OLD" in str_sl:
            logging.info(f'Frame already finalized, skipping...')
        elif "ALREADY_SUBMITTED" in str_sl:
            logging.info(f'Frame already reported, skipping...')
        else:
            logging.error(f'Running tx failed: {str_sl}')
    except:
        logging.error('unexcpected exception, skipping')
        traceback.print_exc()
    finally:
        if isDaemon:
            time.sleep(oracle_sleep_duration)
        else:
            exit(0)
