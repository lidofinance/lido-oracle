import math
import os
import requests
import time
import json
from web3 import Web3, WebsocketProvider, HTTPProvider
from requests.compat import urljoin

SECONDS_PER_SLOT = 12
SLOTS_PER_EPOCH = 1
EPOCH_DURATION = SECONDS_PER_SLOT * SLOTS_PER_EPOCH
HALF_EPOCH_DURATION = EPOCH_DURATION / 2

envs = ['ETH1_NODE', 'ETH2_NODE', 'DEPOOL_CONTRACT', 'ORACLE_CONTRACT', 'MANAGER_PRIV_KEY', 'DEPOOL_ABI_FILE',
        'ORACLE_ABI_FILE', 'REPORT_INTVL_EPOCHS']
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

api_genesis = '/beacon/state/genesis'

if eth1_provider.startswith('http'):
    w3 = Web3(HTTPProvider(eth1_provider))
elif eth1_provider.starstwith('ws'):
    w3 = Web3(WebsocketProvider(eth1_provider))
else:
    print('Unsupported provider')

with open(dp_abi_path, 'r') as file:
    a = file.read()
abi = json.loads(a)
depool = w3.eth.contract(abi=abi['abi'], address=depool_address)

w3.eth.defaultAccount = w3.eth.account.privateKeyToAccount(manager_privkey)

response = requests.get(urljoin(eth2_provider, api_genesis))
genesis_time = response.json()['genesis_time']
current_epoch = math.floor((int(time.time()) - genesis_time) / (SECONDS_PER_SLOT * SLOTS_PER_EPOCH))
print('Oracle daemon start epoch:', current_epoch)

# Wait till the next epoch start
print('Wait next epoch seconds:', (genesis_time + ((current_epoch + 1) * EPOCH_DURATION)) - int(time.time()))
time.sleep((genesis_time + ((current_epoch + 1) * EPOCH_DURATION)) - int(time.time()))
current_epoch += 1
print('The oracle daemon is started!')

while True:
    # Wait for the half of the epoch
    print('Wait for the half of the epoch seconds:',
          genesis_time + (current_epoch * EPOCH_DURATION + HALF_EPOCH_DURATION) - int(time.time()))
    time.sleep(genesis_time + (current_epoch * EPOCH_DURATION + HALF_EPOCH_DURATION) - int(time.time()))
    validators_keys_count = depool.functions.getTotalSigningKeyCount().call({'from': w3.eth.defaultAccount.address})
    if validators_keys_count > 0:
        validators_keys_list = []
        for index in range(validators_keys_count):
            validator_key = depool.functions.getSigningKey(index).call({'from': w3.eth.defaultAccount.address})
            validators_keys_list.append(validator_key[0])
            index += 1

        print('Validators keys list:', validators_keys_list)
        # TODO pushData to Oracle contract
    print('Wait next epoch seconds:', genesis_time + ((current_epoch + 1) * EPOCH_DURATION) - int(time.time()))
    time.sleep(genesis_time + ((current_epoch + 1) * EPOCH_DURATION) - int(time.time()))
    current_epoch += 1
