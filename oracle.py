import json
import logging
import math
import os
import time

from web3 import Web3, WebsocketProvider, HTTPProvider

from beacon import get_beacon, get_actual_slots, get_balances
from contracts import get_validators_keys

logging.basicConfig(level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s',
                    datefmt='%m-%d %H:%M:%S')

SECONDS_PER_SLOT = 12
SLOTS_PER_EPOCH = 32
EPOCH_DURATION = SECONDS_PER_SLOT * SLOTS_PER_EPOCH
ONE_DAY = 60 * 60 * 24

logging.info('Starting oracle daemon')

envs = ['ETH1_NODE', 'ETH2_NODE', 'DEPOOL_CONTRACT', 'ORACLE_CONTRACT', 'MANAGER_PRIV_KEY', 'DEPOOL_ABI_FILE',
        'ORACLE_ABI_FILE', 'REPORT_INTVL_SLOTS']
missing = []
for env in envs:
    if env not in os.environ:
        missing.append(env)
        logging.error('Variable %s is missing', env)

if missing:
    exit(1)

dp_abi_path = os.environ['DEPOOL_ABI_FILE']
dp_oracle_abi_path = os.environ['ORACLE_ABI_FILE']
eth1_provider = os.environ['ETH1_NODE']
eth2_provider = os.environ['ETH2_NODE']
oracle_address = os.environ['ORACLE_CONTRACT']
if not Web3.isChecksumAddress(oracle_address):
    oracle_address = Web3.toChecksumAddress(oracle_address)
depool_address = os.environ['DEPOOL_CONTRACT']
if not Web3.isChecksumAddress(depool_address):
    depool_address = Web3.toChecksumAddress(depool_address)
manager_privkey = os.environ['MANAGER_PRIV_KEY']
report_interval_slots = int(os.environ['REPORT_INTVL_SLOTS'])

beacon = get_beacon(eth2_provider)
logging.info('Connecting to %s', beacon)

provider = None

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

with open(dp_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
depool = w3.eth.contract(abi=abi['abi'], address=depool_address)

with open(dp_oracle_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
oracle = w3.eth.contract(abi=abi['abi'], address=oracle_address)

w3.eth.defaultAccount = w3.eth.account.privateKeyToAccount(manager_privkey)

# Get actual slot and last finalized slot from beacon head data
last_slots = get_actual_slots(beacon, eth2_provider)
last_finalized_slot = last_slots['finalized_slot']
last_finalized_epoch = math.floor(last_finalized_slot / SLOTS_PER_EPOCH)
actual_slot = last_slots['actual_slot']
# Get current epoch
current_epoch = math.floor(actual_slot / SLOTS_PER_EPOCH)
logging.info('Last finalized epoch %s (slot %s)', last_finalized_epoch, last_finalized_slot)
logging.info('Current epoch %s (slot %s)', current_epoch, actual_slot)

# Get first slot of current epoch
start_slot_current_epoch = current_epoch * SLOTS_PER_EPOCH

# Wait till the next epoch start

# Get first slot of next epoch
start_slot_next_epoch = start_slot_current_epoch + SLOTS_PER_EPOCH
next_epoch = math.floor(start_slot_next_epoch / SLOTS_PER_EPOCH)
logging.info('Next epoch %s (first slot %s)', next_epoch, start_slot_next_epoch)

await_time = (start_slot_next_epoch - actual_slot) * SECONDS_PER_SLOT
logging.info('Wait next epoch seconds %s', await_time)
time.sleep(await_time)

# Get actual slot and last finalized slot from beacon head data
last_slots = get_actual_slots(beacon, eth2_provider)
logging.info('The oracle daemon is started!')

# Get last epoch on 7200x slot
before_report_epoch = math.floor(
    last_slots['actual_slot'] / report_interval_slots) * report_interval_slots / SLOTS_PER_EPOCH
logging.info('Previous 7200x slots epoch %s', int(before_report_epoch))

# If the epoch of the last finalized slot is equal to the before_report_epoch, then report balances
if before_report_epoch == math.floor(last_slots['finalized_slot'] / SLOTS_PER_EPOCH):
    validators_keys = get_validators_keys(depool, w3)
    if len(validators_keys) == 0:
        logging.warning('No keys on depool contract')
    sum_balance = get_balances(beacon, eth2_provider, validators_keys)
    oracle.functions.pushData(int(time.time() / ONE_DAY), sum_balance).transact({'from': w3.eth.defaultAccount.address})
    logging.info('Balances pushed!')
else:
    logging.info('Wait next epoch on 7200x slot')

next_report_epoch = int(before_report_epoch + math.floor((report_interval_slots / SLOTS_PER_EPOCH)))
# Sleep while last finalized slot reach expected epoch
logging.info('Next epoch %s first slot %s', next_report_epoch, int(next_report_epoch * SLOTS_PER_EPOCH))
while True:
    # Get actual slot and last finalized slot from beacon head data
    last_slots = get_actual_slots(beacon, eth2_provider)
    calc_epoch = math.floor(last_slots['finalized_slot'] / SLOTS_PER_EPOCH)
    logging.info('Wait epoch %s', int(next_report_epoch))
    logging.info('Current epoch %s', calc_epoch)

    if next_report_epoch == calc_epoch:
        validators_keys = get_validators_keys(depool, w3)
        if len(validators_keys) == 0:
            logging.warning('No keys on depool contract')
        # Get sum of balances
        sum_balance = get_balances(beacon, eth2_provider, validators_keys)
        oracle.functions.pushData(int(time.time() / ONE_DAY), sum_balance).transact(
            {'from': w3.eth.defaultAccount.address})
        next_report_epoch = next_report_epoch + math.floor((report_interval_slots / SLOTS_PER_EPOCH))
        logging.info('Next report epoch after report %s', int(next_report_epoch))
    time.sleep(EPOCH_DURATION)
