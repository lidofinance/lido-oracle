import logging

logging.basicConfig(
    level=logging.INFO, format='%(levelname)8s %(asctime)s <daemon> %(message)s', datefmt='%m-%d %H:%M:%S'
)

def dedup_validators_keys(validators_keys_list):
    return list(set(validators_keys_list))

def get_validators_keys(contract, provider):
    node_operators_count = contract.functions.getNodeOperatorsCount().call()
    
    logging.info(f'Quering NodeOperatorsRegistry...')
    logging.info(f'Node operators in registry: {node_operators_count}')

    validators_keys_list = []
    if node_operators_count > 0:
        for no_id in range(node_operators_count):
            validators_keys_count = contract.functions.getTotalSigningKeyCount(no_id).call()
            
            logging.info(f'Node operator {no_id} -> {validators_keys_count} keys')

            if validators_keys_count > 0:
                for index in range(validators_keys_count):
                    validator_key = contract.functions.getSigningKey(no_id, index).call()
                    validators_keys_list.append(validator_key[0])
                    index += 1
    
    dedupped = dedup_validators_keys(validators_keys_list)
    
    if len(dedupped) != len(validators_keys_list):
        logging.error(f'Alert! Validators keys contain duplicates.')

    return dedupped
