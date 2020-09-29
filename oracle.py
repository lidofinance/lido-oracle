import math
import os
import time
import json

from web3 import Web3, WebsocketProvider, HTTPProvider

from beacon import get_beacon, get_actual_slots
from contracts import get_validators_keys

SECONDS_PER_SLOT = 12
SLOTS_PER_EPOCH = 32
EPOCH_DURATION = SECONDS_PER_SLOT * SLOTS_PER_EPOCH

envs = ['ETH1_NODE', 'ETH2_NODE', 'DEPOOL_CONTRACT', 'ORACLE_CONTRACT', 'MANAGER_PRIV_KEY', 'DEPOOL_ABI_FILE',
        'ORACLE_ABI_FILE', 'REPORT_INTVL_SLOTS']
for env in envs:
    if env not in os.environ:
        print(env, 'is missing')
        exit(1)

dp_abi_path = os.environ['DEPOOL_ABI_FILE']
dp_oracle_abi_path = os.environ['ORACLE_ABI_FILE']
eth1_provider = os.environ['ETH1_NODE']
eth2_provider = os.environ['ETH2_NODE']
oracle_address = os.environ['ORACLE_CONTRACT']
depool_address = os.environ['DEPOOL_CONTRACT']
manager_privkey = os.environ['MANAGER_PRIV_KEY']
report_interval_slots = int(os.environ['REPORT_INTVL_SLOTS'])

beacon = get_beacon(eth2_provider)
print(beacon)

provider = None

if eth1_provider.startswith('http'):
    provider = HTTPProvider(eth1_provider)
elif eth1_provider.starstwith('ws'):
    provider = WebsocketProvider(eth1_provider)
else:
    print('Unsupported provider')
    exit(1)

w3 = Web3(provider)

if not w3.isConnected():
    print('ETH Node connection error')
    exit(1)

with open(dp_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
depool = w3.eth.contract(abi=abi['abi'], address=depool_address)

w3.eth.defaultAccount = w3.eth.account.privateKeyToAccount(manager_privkey)

# Get actual slot and last finalized slot from beacon head data
last_slots = get_actual_slots(beacon, eth2_provider)
last_finalized_slot = last_slots['finalized_slot']
actual_slot = last_slots['actual_slot']
print('Last finalized slot', last_finalized_slot)
print('Actual slot', actual_slot)

# Get current epoch
current_epoch = math.floor(actual_slot / SLOTS_PER_EPOCH)
print('Oracle daemon start epoch:', current_epoch)

# Get first slot of current epoch
start_slot_current_epoch = current_epoch * SLOTS_PER_EPOCH

# Wait till the next epoch start

# Get first slot of next epoch
start_slot_next_epoch = start_slot_current_epoch + SLOTS_PER_EPOCH
print('Next epoch first slot', start_slot_next_epoch)

await_time = (start_slot_next_epoch - actual_slot) * SECONDS_PER_SLOT
print('Wait next epoch seconds:', await_time)
time.sleep(await_time)

# Get actual slot and last finalized slot from beacon head data
last_slots = get_actual_slots(beacon, eth2_provider)
print('The oracle daemon is started!')

# Get last epoch on 7200x slot
before_report_epoch = math.floor(
    last_slots['actual_slot'] / report_interval_slots) * report_interval_slots / SLOTS_PER_EPOCH
print('before 7200 slots epoch', before_report_epoch)

# If the epoch of the last finalized slot is equal to the before_report_epoch, then report balances
if before_report_epoch == math.floor(last_slots['finalized_slot'] / SLOTS_PER_EPOCH):
    validators_keys = get_validators_keys(depool, w3)
    # TODO get balances and push to oracle
    print(validators_keys)
else:
    print('Wait next epoch on 7200x slot')

next_report_epoch = math.floor(before_report_epoch + (report_interval_slots / SLOTS_PER_EPOCH))
# Sleep while last finalized slot reach expected epoch
print('Next slot first slot', next_report_epoch * SLOTS_PER_EPOCH)
while True:
    time.sleep(EPOCH_DURATION)
    # Get actual slot and last finalized slot from beacon head data
    last_slots = get_actual_slots(beacon, eth2_provider)
    calc_epoch = math.floor(last_slots['finalized_slot'] / SLOTS_PER_EPOCH)
    print('Wait epoch', next_report_epoch)
    print('Now epoch', calc_epoch)

    if next_report_epoch == calc_epoch:
        validators_keys = get_validators_keys(depool, w3)
        # TODO get balances and push to oracle
        next_report_epoch = math.floor(before_report_epoch + (report_interval_slots / SLOTS_PER_EPOCH))
        print('Next report epoch after report', next_report_epoch)
