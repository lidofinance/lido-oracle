def get_validators_keys(contract, provider):
    validators_keys_count = contract.functions.getTotalSigningKeyCount().call({'from': provider.eth.defaultAccount.address})
    if validators_keys_count > 0:
        validators_keys_list = []
        for index in range(validators_keys_count):
            validator_key = contract.functions.getSigningKey(index).call({'from': provider.eth.defaultAccount.address})
            validators_keys_list.append(validator_key[0])
            index += 1
        return validators_keys_list
    else:
        print('No keys on depool contract')
