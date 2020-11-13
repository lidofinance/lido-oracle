def get_validators_keys(contract, provider):
    node_operators_count = contract.functions.getNodeOperatorsCount().call(
        {'from': provider.eth.defaultAccount.address}
    )
    validators_keys_list = []
    if node_operators_count > 0:
        for no_id in range(node_operators_count):
            validators_keys_count = contract.functions.getTotalSigningKeyCount(no_id).call(
                {'from': provider.eth.defaultAccount.address}
            )
            if validators_keys_count > 0:
                for index in range(validators_keys_count):
                    validator_key = contract.functions.getSigningKey(no_id, index).call(
                        {'from': provider.eth.defaultAccount.address}
                    )
                    validators_keys_list.append(validator_key[0])
                    index += 1
    return validators_keys_list
