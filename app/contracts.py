# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import typing as t
import logging
import os

from lido import Lido

DEFAULT_MAX_MULTICALL = 30
MAX_MULTICALL = int(os.environ.get('MAX_MULTICALL', DEFAULT_MAX_MULTICALL))


def dedup_validators_keys(validators_keys_list):
    return list(set(validators_keys_list))


def get_total_supply(contract):  # fixme
    print(f'{contract.all_functions()=}')
    return contract.functions.totalSupply().call()


def get_validators_keys(w3, registry_address) -> t.List[bytes]:
    """ fetch keys
    apply crypto validation
    apply duplicates finding
    raise on any check's fail
    return list of keys
    """
    lido = Lido(
        w3,
        registry_address=registry_address,
        max_multicall=MAX_MULTICALL)

    operators_data = lido.get_operators_data()

    operators = lido.get_operators_keys(operators_data)

    keys = []
    for op in operators:
        for key_item in op['keys']:
            key = key_item['key']
            keys.append(key)
    return keys
