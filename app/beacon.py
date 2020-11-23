import base64
import binascii
import datetime
import logging
from datetime import timezone

import requests
from requests.compat import urljoin

logging.basicConfig(
    level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s', datefmt='%m-%d %H:%M:%S'
)

def get_beacon(provider, slots_per_epoch):
    version = requests.get(urljoin(provider, 'eth/v1/node/version')).text
    if 'Lighthouse' in version:
        return Lighthouse(provider, slots_per_epoch)
    version = requests.get(urljoin(provider, 'eth/v1alpha1/node/version')).text
    if 'Prysm' in version:
        logging.error(f'Not supporting Prysm beacon node')
        exit(1)
        # TODO: fix me 
        # return Prysm(provider, slots_per_epoch) 
    raise ValueError('Unknown beacon')


class Lighthouse:
    api_version = 'eth/v1/node/version'
    api_genesis = 'eth/v1/beacon/genesis'
    api_beacon_head_finality_checkpoints = 'eth/v1/beacon/states/head/finality_checkpoints'
    api_beacon_head_finalized = 'eth/v1/beacon/headers/finalized'
    api_beacon_head_actual = 'eth/v1/beacon/headers/head'
    api_get_balance = 'eth/v1/beacon/states/{}/validators/{}'
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
        
        logging.info(f'Fetching validators from Beacon node...')
        balance_list = []
        found_on_beacon_pubkeys = []
        for pubkey in pubkeys:
            json = requests.get(
                urljoin(self.url, self.api_get_balance.format(slot, pubkey))
            ).json()
            
            if 'data' in json:
                balance_list.append(int(json['data']['balance']))
                found_on_beacon_pubkeys.append(json['data']['validator']['pubkey'])

        # Log all validators along with balance      
        logging.info(f'Validator balances on beacon for slot {slot}')
        for pubkey, balance in zip(found_on_beacon_pubkeys, balance_list):
            logging.info(f'{pubkey} -> {balance} Gwei')
        balances = sum(balance_list)
        logging.info(f'Validator balances sum: {balances} Gwei')

        # Convert Gwei to wei
        balances *= 10 ** 9
        total_validators_on_beacon = len(found_on_beacon_pubkeys)

        return (balances, total_validators_on_beacon)


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
        genesis_time = datetime.datetime.strptime(genesis_time, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
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
