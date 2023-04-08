# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import binascii
import logging
from typing import Tuple, Iterable
from urllib.parse import urljoin

from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout

from urllib3.util import Retry

from exceptions import BeaconConnectionTimeoutException


DEFAULT_TIMEOUT = 60
LONG_TIMEOUT = 60 * 20


retry_strategy = Retry(
    total=5,
    status_forcelist=[418, 429, 500, 502, 503, 504],
    backoff_factor=5,
)

adapter = HTTPAdapter(max_retries=retry_strategy)
session = Session()
session.mount("https://", adapter)
session.mount("http://", adapter)


class ValidatorStatus:
    PENDING_INITIALIZED = 'pending_initialized'
    PENDING_QUEUED = 'pending_queued'
    ACTIVE_ONGOING = 'active_ongoing'
    ACTIVE_EXITING = 'active_exiting'
    ACTIVE_SLASHED = 'active_slashed'
    EXITED_UNSLASHED = 'exited_unslashed'
    EXITED_SLASHED = 'exited_slashed'
    WITHDRAWAL_POSSIBLE = 'withdrawal_possible'
    WITHDRAWAL_DONE = 'withdrawal_done'
    ACTIVE = 'active'
    PENDING = 'pending'
    EXITED = 'exited'
    WITHDRAWAL = 'withdrawal'


def proxy_connect_timeout_exception(func):
    def inner(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ConnectTimeout as exc:
            raise BeaconConnectionTimeoutException() from exc

    return inner


class BeaconBlockNotFoundError(Exception):
    pass


class NoNonMissedSlotsFoundException(Exception):
    pass


class BeaconChainClient:
    api_beacon_block = 'eth/v2/beacon/blocks/{}'
    api_beacon_head_finality_checkpoints = 'eth/v1/beacon/states/head/finality_checkpoints'
    api_get_validators = 'eth/v1/beacon/states/{}/validators'

    def __init__(self, url, slots_per_epoch):
        self.url = url
        self.slots_per_epoch = slots_per_epoch

    @proxy_connect_timeout_exception
    def get_block_by_beacon_slot(self, slot):
        response = session.get(urljoin(self.url, self.api_beacon_block.format(slot)), timeout=DEFAULT_TIMEOUT)

        if response.status_code == 404:
            raise BeaconBlockNotFoundError()

        try:
            return int(response.json()['data']['message']['body']['execution_payload']['block_number'])
        except KeyError as error:
            logging.error(f'Response [{response.status_code}] with text: {str(response.text)} was returned.')
            raise error

    def get_slot_for_report(self, ref_slot: int, epochs_per_frame: int, slots_per_epoch: int):
        for slot_num in range(ref_slot, ref_slot - epochs_per_frame * slots_per_epoch, -1):
            try:
                self.get_block_by_beacon_slot(slot_num)
            except BeaconBlockNotFoundError as error:
                logging.warning({'msg': f'Slot {slot_num} missed. Looking previous one...', 'error': str(error)})
            else:
                return slot_num

        raise NoNonMissedSlotsFoundException('No slots found for report. Probably problem with CL node.')

    @proxy_connect_timeout_exception
    def get_finalized_epoch(self):
        response = session.get(urljoin(self.url, self.api_beacon_head_finality_checkpoints), timeout=DEFAULT_TIMEOUT)
        try:
            return int(response.json()['data']['finalized']['epoch'])
        except KeyError as error:
            logging.error(f'Response [{response.status_code}] with text: {str(response.text)} was returned.')
            raise KeyError from error

    @proxy_connect_timeout_exception
    def get_balances(self, slot, keys_list) -> Tuple[int, int, int]:
        all_validators = self._fetch_balances(slot)
        logging.info(f'Validator balances on beacon for slot: {slot}')

        validator_pub_keys = self._from_bytes_to_pub_keys(keys_list)

        validators_count = 0
        total_balance = 0
        active_validators_balance = 0

        for validator in all_validators:
            if validator['validator']['pubkey'] in validator_pub_keys:
                validators_count += 1
                total_balance += int(validator['balance'])

                if validator['status'] in [ValidatorStatus.ACTIVE, ValidatorStatus.ACTIVE_ONGOING]:
                    active_validators_balance += int(validator['balance'])

        # Convert Gwei to wei
        total_balance *= 10**9
        active_validators_balance *= 10**9

        return total_balance, validators_count, active_validators_balance

    @staticmethod
    def _from_bytes_to_pub_keys(keys_list):
        # To make search faster instead of dict we use set
        return set('0x' + binascii.hexlify(key).decode() for key in keys_list)

    def _fetch_balances(self, slot) -> Iterable:
        logging.info('Fetching validators from Beacon node...')
        val_url = urljoin(self.url, self.api_get_validators.format(slot))
        logging.info(f'using url "{val_url}"')

        response = session.get(val_url, timeout=LONG_TIMEOUT)

        try:
            return response.json()['data']
        except KeyError as error:
            logging.error(f'Response [{response.status_code}] with text: {str(response.text)} was returned.')
            raise KeyError from error
