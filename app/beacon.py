import base64
import binascii
import json

import requests
from requests.compat import urljoin

api_version_lighthouse = 'eth/v1/node/version'
api_version_prism = 'eth/v1alpha1/node/version'

API = {
    'Lighthouse': {
        'api_version': 'eth/v1/node/version',
        'beacon_head_finalized': 'eth/v1/beacon/headers/finalized',
        'beacon_head_actual': 'eth/v1/beacon/headers/head',
        'get_balances': '​eth/v1/beacon/states/{}/validators',
        'get_slot': 'eth/v1/beacon/states/{}/root'
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
        beacon_head_actual = API['Lighthouse']['beacon_head_actual']
        response = requests.get(urljoin(provider, beacon_head_actual)).json()
        actual_slots['actual_slot'] = int(response['data']['header']['message']['slot'])

        beacon_head_finalized = API['Lighthouse']['beacon_head_finalized']
        response = requests.get(urljoin(provider, beacon_head_finalized)).json()
        actual_slots['finalized_slot'] = int(response['data']['header']['message']['slot'])
        return actual_slots
    if beacon == "Prysm":
        beacon_head = API['Prysm']['beacon_head']
        response = requests.get(urljoin(provider, beacon_head)).json()
        actual_slots['actual_slot'] = int(response['headSlot'])
        actual_slots['finalized_slot'] = int(response['finalizedSlot'])
        return actual_slots


def get_balances_lighthouse(eth2_provider, slot, key_list):
    payload = {}
    pubkeys = []
    for key in key_list:
        pubkeys.append('0x' + binascii.hexlify(key).decode())

    payload['id'] = pubkeys
    response = requests.get(urljoin(eth2_provider, API['Lighthouse']['get_balances'].format(slot)))
    balance_list = []
    for validator in response.json()['data']:
        if validator['validator']['pubkey'] in pubkeys:
            balance_list.append(int(validator['balance']))
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


def get_slot_or_epoch(beacon, epoch, slots_per_epoch):
    if beacon == 'Lighthouse':
        return epoch * slots_per_epoch
    elif beacon == 'Prysm':
        # Rounding when using non-standard epoch lengths
        return epoch
    raise ValueError('Unknown beacon name')
