# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import base64
import binascii
import datetime
import logging
import math
from datetime import timezone

import requests
from requests.compat import urljoin

logging.basicConfig(
    level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)


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
    api_beacon_head_finality_checkpoints = 'eth/v1/beacon/states/head/finality_checkpoints'
    api_beacon_head_finalized = 'eth/v1/beacon/headers/finalized'
    api_beacon_head_actual = 'eth/v1/beacon/headers/head'
    api_get_balances = 'eth/v1/beacon/states/{}/validators'
    api_get_slot = 'eth/v1/beacon/states/{}/root'

    def __init__(self, url, slots_per_epoch):
        self.url = url
        self.slots_per_epoch = slots_per_epoch
        self.version = requests.get(urljoin(url, self.api_version)).json()

    def get_finalized_epoch(self):
        return int(requests.get(urljoin(self.url, self.api_beacon_head_finality_checkpoints)).json()['data']['finalized']['epoch'])

    def get_genesis(self):
        return int(requests.get(urljoin(self.url, self.api_genesis)).json()['data']['genesis_time'])

    def get_actual_slot(self):
        actual_slots = {}
        response = requests.get(urljoin(self.url, self.api_beacon_head_actual)).json()
        actual_slots['actual_slot'] = int(response['data']['header']['message']['slot'])
        response = requests.get(urljoin(self.url, self.api_beacon_head_finalized)).json()
        actual_slots['finalized_slot'] = int(response['data']['header']['message']['slot'])
        return actual_slots

    def _convert_key_list_to_str_arr(self, key_list):
        pubkeys = []
        for key in key_list:
            pubkeys.append('0x' + binascii.hexlify(key).decode())

        return pubkeys

    def get_balances(self, slot, key_list):
        pubkeys = self._convert_key_list_to_str_arr(key_list)

        logging.info('Fetching validators from Beacon node...')
        response_json = requests.get(urljoin(self.url, self.api_get_balances.format(slot))).json()
        balance_list = []
        found_on_beacon_pubkeys = []
        logging.info(f'Validator balances on beacon for slot: {slot}')
        active_validators_balance = 0
        for validator in response_json['data']:
            pubkey = validator['validator']['pubkey']
            # Log all validators along with balance
            if pubkey in pubkeys:
                validator_balance = int(validator['balance'])

                if validator['status'] == 'active':
                    active_validators_balance += validator_balance

                balance_list.append(validator_balance)
                found_on_beacon_pubkeys.append(validator['validator']['pubkey'])
                logging.info(f'Pubkey: {pubkey[:12]} Balance: {validator_balance} Gwei')
            elif validator['status'] == 'UNKNOWN':
                logging.warning(f'Pubkey {pubkey[:12]} status UNKNOWN')
        balance = sum(balance_list)

        # Convert Gwei to wei
        balance *= 10 ** 9
        active_validators_balance *= 10 ** 9

        validators = len(found_on_beacon_pubkeys)
        return balance, validators, active_validators_balance


class Prysm:
    api_version = 'eth/v1alpha1/node/version'
    api_genesis = 'eth/v1alpha1/node/genesis'
    api_beacon_head = 'eth/v1alpha1/beacon/chainhead'
    api_get_balances = 'eth/v1alpha1/validators/balances'

    def __init__(self, url, slots_per_epoch):
        self.url = url
        self.slots_per_epoch = slots_per_epoch
        self.version = requests.get(urljoin(url, self.api_version)).json()

    def get_finalized_epoch(self):
        finalized_epoch = int(requests.get(urljoin(self.url, self.api_beacon_head)).json()['finalizedEpoch'])
        return finalized_epoch

    def get_genesis(self):
        genesis_time = requests.get(urljoin(self.url, self.api_genesis)).json()['genesisTime']
        genesis_time = datetime.datetime.strptime(genesis_time, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        genesis_time = int(genesis_time.timestamp())
        return genesis_time

    def get_actual_slot(self):
        actual_slots = {}
        response = requests.get(urljoin(self.url, self.api_beacon_head)).json()
        actual_slots['actual_slot'] = int(response['headSlot'])
        actual_slots['finalized_slot'] = int(response['finalizedSlot'])
        return actual_slots

    def get_balances(self, slot, key_list):
        params = {}
        pubkeys = []
        found_on_beacon_pubkeys = []
        balance_list = []
        key_dict = {}
        for key in key_list:
            base64_key = base64.b64encode(key).decode()
            hex_key = '0x' + binascii.hexlify(key).decode()
            key_dict[base64_key] = hex_key[:12]
            pubkeys.append(base64_key)

        epoch = math.ceil(slot / self.slots_per_epoch)  # Round up in case of missing slots

        active_validators_balance = 0

        for pk in pubkeys:
            params['publicKeys'] = pk
            params['epoch'] = epoch
            response = requests.get(urljoin(self.url, self.api_get_balances), params=params)
            if 'error' in response.json():
                logging.error(f'Pubkey {key_dict[pk]} return error')
                continue
            validator = response.json()['balances'][0]

            if validator['publicKey'] in pubkeys:
                found_on_beacon_pubkeys.append(validator['publicKey'])
                balance = int(validator['balance'])
                if validator['status'] == 'ACTIVE':
                    active_validators_balance += balance

                balance_list.append(balance)
                logging.info(f'Pubkey: {key_dict[pk]} Balance: {balance} Gwei')
            elif validator['status'] == 'UNKNOWN':
                logging.warning(f'Pubkey {key_dict[pk]} status UNKNOWN')

        balances = sum(balance_list)
        # Convert Gwei to wei
        balances *= 10 ** 9
        active_validators_balance *= 10 ** 9
        total_validators_on_beacon = len(found_on_beacon_pubkeys)

        return balances, total_validators_on_beacon, active_validators_balance
