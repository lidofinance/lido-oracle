import logging

logging.basicConfig(
    level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s', datefmt='%m-%d %H:%M:%S'
)

def dedup_validators_keys(validators_keys_list):
    return list(set(validators_keys_list))

def get_validators_keys(contract, provider):
    node_operators_count = contract.functions.getNodeOperatorsCount().call(
        {'from': provider.eth.defaultAccount.address}
    )
    
    logging.info(f'Quering NodeOperatorsRegistry...')
    logging.info(f'Node operators in registry: {node_operators_count}')

    validators_keys_list = []
    if node_operators_count > 0:
        for no_id in range(node_operators_count):
            validators_keys_count = contract.functions.getTotalSigningKeyCount(no_id).call(
                {'from': provider.eth.defaultAccount.address}
            )

            validators_unused_keys_count = contract.functions.getUnusedSigningKeyCount(no_id).call(
                {'from': provider.eth.defaultAccount.address}
            )
            
            validators_used_key_count = validators_keys_count - validators_unused_keys_count

            logging.info(f'Node operator {no_id} -> {validators_used_key_count}/{validators_keys_count} keys')

            if validators_used_key_count > 0:
                for index in range(validators_keys_count):
                    validator_key = contract.functions.getSigningKey(no_id, index).call(
                        {'from': provider.eth.defaultAccount.address}
                    )
                    validators_keys_list.append(validator_key[0])
                    index += 1

    dedupped = dedup_validators_keys(validators_keys_list)
    
    if len(dedupped) != len(validators_keys_list):
        logging.error(f'Alert! Validators keys contain duplicates.')

    return dedupped
