# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

import logging


def dedup_validators_keys(validators_keys_list):
    return list(set(validators_keys_list))


def get_total_supply(contract):
    print(f'{contract.all_functions()=}')
    return contract.functions.totalSupply().call()


def get_validators_keys(contract):
    node_operators_count = contract.functions.getNodeOperatorsCount().call()

    logging.info('Quering NodeOperatorsRegistry...')
    logging.info(f'Node operators in registry: {node_operators_count}')

    validators_keys_list = []
    if node_operators_count > 0:
        for no_id in range(node_operators_count):
            validators_keys_count = contract.functions.getTotalSigningKeyCount(no_id).call()

            logging.info(f'Node operator ID: {no_id} Keys: {validators_keys_count}')

            if validators_keys_count > 0:
                for index in range(validators_keys_count):
                    validator_key = contract.functions.getSigningKey(no_id, index).call()
                    validators_keys_list.append(validator_key[0])
                    index += 1

    dedupped = dedup_validators_keys(validators_keys_list)

    if len(dedupped) != len(validators_keys_list):
        logging.error('Alert! Validators keys contain duplicates.')

    return dedupped
