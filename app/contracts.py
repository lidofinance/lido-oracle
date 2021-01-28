# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import typing as t
import logging

from lido import fetch_and_validate


def dedup_validators_keys(validators_keys_list):
    return list(set(validators_keys_list))


def get_total_supply(contract):  # fixme
    print(f'{contract.all_functions()=}')
    return contract.functions.totalSupply().call()


def get_validators_keys(contract) -> t.List[bytes]:
    """ fetch keys
    apply crypto validation
    apply duplicates finding
    raise on any check's fail
    return list of keys
    """
    operators = fetch_and_validate(registry_address=contract.address)
    keys = []
    for op in operators:
        for key_item in op['keys']:
            key = key_item['key']
            if key_item['duplicate']:
                raise ValueError(f'bad key {key_item}')
            if not key_item['valid_signature']:
                raise ValueError(f'invalid signature {key_item}')
            keys.append(key)
    return keys
