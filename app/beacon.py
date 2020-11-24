# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import base64
import binascii
import datetime

import requests
from requests.compat import urljoin


def get_beacon(provider, slots_per_epoch):
    version = requests.get(urljoin(provider, 'eth/v1/node/version')).text
    if 'Lighthouse' in version:
        return Lighthouse(provider, slots_per_epoch)
    version = requests.get(urljoin(provider, 'eth/v1alpha1/node/version')).text
    if 'Prysm' in version:
        return Prysm(provider, slots_per_epoch)
    raise ValueError('Unknown beacon')


class Lighthouse:
    api_version = 'eth/v1/node/version'
    api_genesis = 'eth/v1/beacon/genesis'
    api_beacon_head_finalized = 'eth/v1/beacon/headers/finalized'
    api_beacon_head_actual = 'eth/v1/beacon/headers/head'
    api_get_balances = 'eth/v1/beacon/states/{}/validators'
    api_get_slot = 'eth/v1/beacon/states/{}/root'

    def __init__(self, url, slots_per_epoch):
        self.url = url
        self.slots_per_epoch = slots_per_epoch
        self.version = requests.get(urljoin(url, self.api_version)).json()

    def get_genesis(self):
        return int(requests.get(urljoin(self.url, self.api_genesis)).json()['data']['genesis_time'])

    def get_actual_slot(self):
        actual_slots = {}
        response = requests.get(urljoin(self.url, self.api_beacon_head_actual)).json()
        actual_slots['actual_slot'] = int(response['data']['header']['message']['slot'])
        response = requests.get(urljoin(self.url, self.api_beacon_head_finalized)).json()
        actual_slots['finalized_slot'] = int(response['data']['header']['message']['slot'])
        return actual_slots

    def get_balances(self, epoch, key_list):
        payload = {}
        pubkeys = []
        slot = epoch * self.slots_per_epoch
        for key in key_list:
            pubkeys.append('0x' + binascii.hexlify(key).decode())

        payload['id'] = pubkeys
        response = requests.get(urljoin(self.url, self.api_get_balances.format(slot)))
        balance_list = []
        for validator in response.json()['data']:
            if validator['validator']['pubkey'] in pubkeys:
                balance_list.append(int(validator['balance']))
        balances = sum(balance_list)
        # Convert Gwei to wei
        balances *= 10 ** 9
        return balances


class Prysm:
    api_version = 'eth/v1alpha1/node/version'
    api_genesis = 'eth/v1alpha1/node/genesis'
    api_beacon_head = 'eth/v1alpha1/beacon/chainhead'
    api_get_balances = 'eth/v1alpha1/validators/balances'

    def __init__(self, url, slots_per_epoch):
        self.url = url
        self.slots_per_epoch = slots_per_epoch
        self.version = requests.get(urljoin(url, self.api_version)).json()

    def get_genesis(self):
        genesis_time = requests.get(urljoin(self.url, self.api_genesis)).json()['genesisTime']
        genesis_time = datetime.datetime.strptime(genesis_time, '%Y-%m-%dT%H:%M:%SZ')
        genesis_time = int(genesis_time.timestamp())
        return genesis_time

    def get_actual_slot(self):
        actual_slots = {}
        response = requests.get(urljoin(self.url, self.api_beacon_head)).json()
        actual_slots['actual_slot'] = int(response['headSlot'])
        actual_slots['finalized_slot'] = int(response['finalizedSlot'])
        return actual_slots

    def get_balances(self, epoch, key_list):
        params = {}
        pubkeys = []
        for key in key_list:
            pubkeys.append(base64.b64encode(key).decode())
        params['publicKeys'] = pubkeys
        params['epoch'] = epoch
        response = requests.get(urljoin(self.url, self.api_get_balances), params=params)
        balance_list = []
        for validator in response.json()['balances']:
            balance_list.append(int(validator['balance']))
        balances = sum(balance_list)
        # Convert Gwei to wei
        balances *= 10 ** 9
        return balances
