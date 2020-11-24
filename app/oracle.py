import binascii
import json
import logging
import os
import time

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
await_time_in_sec = os.getenv('SLEEP', 60)

run_as_daemon = int(os.getenv('DAEMON', 0))

dry_run = member_privkey is None

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

if not dry_run:
    account = w3.eth.account.privateKeyToAccount(member_privkey)

# Get Pool contract
with open(pool_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
pool = w3.eth.contract(abi=abi['abi'], address=pool_address)

# Get Oracle contract
oracle_address = pool.functions.getOracle().call()

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
slots_per_epoch = beacon_spec[1]
seconds_per_slot = beacon_spec[2]

beacon = get_beacon(beacon_provider, slots_per_epoch)

if dry_run:
    logging.warning('Running in a DRY RUN mode!')

if run_as_daemon:
    logging.info('=====The oracle started as daemon!=====')
else:
    logging.info('=====The oracle started in single run mode!=====')

logging.info('============ CONFIGURATION ============')
logging.info(f'ETH1 Node: {eth1_provider}')
logging.info(f'Beacon Node: {beacon_provider}')
logging.info('Connecting to %s', beacon.__class__.__name__)
logging.info(f'Pool contract address: {pool_address}')
logging.info(f'Oracle contract address: {oracle_address}')
logging.info(f'Registry contract address: {registry_address}')
if dry_run:
    logging.info(f'Member account not set in DRY RUN mode')
else:
    logging.info(f'Member account: {account.address}')

logging.info(f'Seconds per slot: {seconds_per_slot}')
logging.info(f'Slots per epoch: {slots_per_epoch}')
logging.info('=======================================')


def build_report_beacon_tx(reportable_epoch, sum_balance, validators_on_beacon):
    return oracle.functions.reportBeacon(
        reportable_epoch, sum_balance, validators_on_beacon
    ).buildTransaction({'from': account.address, 'gas': GAS_LIMIT})


def sign_and_send_tx(tx):
    logging.info('Prepearing to send a tx...')

    if not run_as_daemon:
        time.sleep(5)  # To be able to Ctrl + C

    tx['nonce'] = w3.eth.getTransactionCount(
        account.address
    )  # Get correct transaction nonce for sender from the node
    signed = w3.eth.account.signTransaction(tx, account.privateKey)

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

    # Get the frame and validators keys from ETH1 side
    current_frame = oracle.functions.getCurrentFrame().call()
    reportable_epoch = current_frame[0]
    logging.info(f'Reportable epoch: {reportable_epoch}')
    validators_keys = get_validators_keys(registry, w3)
    logging.info(f'Total validator keys in registry: {len(validators_keys)}')

    # Wait for the epoch finalization on the beacon chain
    while True:

        finalized_epoch = beacon.get_finalized_epoch()
        slot = reportable_epoch * slots_per_epoch

        if reportable_epoch > finalized_epoch:
            # The reportable epoch received from the contract
            # is not finalized on the beacon chain so we are waiting
            logging.info(
                f'Reportable epoch ({reportable_epoch}) is greater than Beacon chain finalized (epoch: {finalized_epoch} slot: {slot}). Wait {await_time_in_sec} s'
            )
            time.sleep(await_time_in_sec)
            continue
        else:
            logging.info(f'Reportable epoch ({reportable_epoch}) is finalized on beacon chain.')
            break

    # At this point the slot is finalized on the beacon
    # so we are able to retrieve validators set and balances
    sum_balance, validators_on_beacon = beacon.get_balances(slot, validators_keys)
    logging.info(f'ReportBeacon transaction arguments:')
    logging.info(f'Reportable epoch: {reportable_epoch}')
    logging.info(f'Sum balance in wei: {sum_balance}')
    logging.info(f'Validators number on Beacon chain: {validators_on_beacon}')
    logging.info(f'Tx call data: oracle.reportBeacon({reportable_epoch}, {sum_balance}, {validators_on_beacon})')
    if not dry_run:
        # Create the tx and execute it locally to check validity
        tx = build_report_beacon_tx(reportable_epoch, sum_balance, validators_on_beacon)
        w3.eth.call(tx)
        logging.info('Calling tx locally is succeeded. Sending it to the network')
        sign_and_send_tx(tx)
    else:
        logging.info('DRY RUN mode. The tx hasn\'t been actually sent to the oracle contract!')

    if run_as_daemon:
        logging.info(f'Process not daemonized so we exit.')
        break
