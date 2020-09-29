import requests

from requests.compat import urljoin

api_version_lighthouse = 'node/version'
api_version_prism = 'eth/v1alpha1/node/version'

API = {
    'Lighthouse': {
        'api_version': 'node/version',
        'beacon_head': 'beacon/head',
    },
    'Prysm': {
        'api_version': 'eth/v1alpha1/node/version',
        'beacon_head': 'eth/v1alpha1/beacon/chainhead',
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

