import base64
import binascii
import json
import math

import requests
from requests.compat import urljoin

api_version_lighthouse = 'node/version'
api_version_prism = 'eth/v1alpha1/node/version'

API = {
    'Lighthouse': {
        'api_version': 'node/version',
        'beacon_head': 'beacon/head',
        'get_balances': 'beacon/validators',
        'get_slot': 'beacon/state_root'
    },
    'Prysm': {
        'api_version': 'eth/v1alpha1/node/version',
        'beacon_head': 'eth/v1alpha1/beacon/chainhead',
        'get_balances': 'eth/v1alpha1/validators/balances'
    }
}


def get_beacon(provider):
    version = requests.get(urljoin(provider, API['Lighthouse']['api_version'])).text
    if 'Lighthouse' in version:
        return 'Lighthouse'
    version = requests.get(urljoin(provider, API['Prysm']['api_version'])).text
    if 'Prysm' in version:
        return 'Prysm'
    return 'None'


def get_actual_slots(beacon, provider):
    actual_slots = {}
    if beacon == "Lighthouse":
        beacon_head = API['Lighthouse']['beacon_head']
        response = requests.get(urljoin(provider, beacon_head)).json()
        actual_slots['actual_slot'] = response['slot']
        actual_slots['finalized_slot'] = response['finalized_slot']
        return actual_slots
    if beacon == "Prysm":
        beacon_head = API['Prysm']['beacon_head']
        response = requests.get(urljoin(provider, beacon_head)).json()
        actual_slots['actual_slot'] = response['headSlot']
        actual_slots['finalized_slot'] = response['finalizedSlot']
        return actual_slots


def get_balances_lighthouse(eth2_provider, slot, key_list):
    state_root = requests.get(urljoin(eth2_provider, API['Lighthouse']['get_slot']), params={'slot': slot}).json()
    payload = {}
    pubkeys = []
    for key in key_list:
        pubkeys.append('0x' + binascii.hexlify(key).decode())
    payload['pubkeys'] = pubkeys
    payload['state_root'] = state_root
    data = json.dumps(payload)
    response = requests.post(urljoin(eth2_provider, API['Lighthouse']['get_balances']), data=data)
    balance_list = []
    for validator in response.json():
        balance_list.append(validator['balance'])
    balances = sum(balance_list)
    # Convert Gwei to wei
    balances *= 10 ** 9
    return balances


def get_balances_prysm(eth2_provider, epoch, key_list):
    payload = {}
    pubkeys = []
    for key in key_list:
        pubkeys.append(base64.b64encode(key).decode())
    payload['publicKeys'] = pubkeys
    payload['epoch'] = epoch
    response = requests.get(urljoin(eth2_provider, API['Prysm']['get_balances']), params=payload)
    balance_list = []
    for validator in response.json()['balances']:
        balance_list.append(int(validator['balance']))
    balances = sum(balance_list)
    # Convert Gwei to wei
    balances *= 10 ** 9
    return balances


def get_balances(beacon, eth2_provider, target, key_list):
    if beacon == 'Lighthouse':
        return get_balances_lighthouse(eth2_provider, target, key_list)
    if beacon == 'Prysm':
        return get_balances_prysm(eth2_provider, target, key_list)
    raise ValueError('Unknown beacon name')


def get_slot_or_epoch(beacon, slot, slots_per_epoch):
    if beacon == 'Lighthouse':
        return slot
    elif beacon == 'Prysm':
        # Rounding when using non-standard epoch lengths
        return math.floor(slot / slots_per_epoch)
    raise ValueError('Unknown beacon name')
