# SPDX-FileCopyrightText: 2020 Lido <info@lido.fi>

# SPDX-License-Identifier: GPL-3.0

def get_validators_keys(contract, provider):
    staking_providers_count = contract.functions.getStakingProvidersCount().call(
        {'from': provider.eth.defaultAccount.address}
    )
    validators_keys_list = []
    if staking_providers_count > 0:
        for sp_id in range(staking_providers_count):
            validators_keys_count = contract.functions.getTotalSigningKeyCount(sp_id).call(
                {'from': provider.eth.defaultAccount.address}
            )
            if validators_keys_count > 0:
                for index in range(validators_keys_count):
                    validator_key = contract.functions.getSigningKey(sp_id, index).call(
                        {'from': provider.eth.defaultAccount.address}
                    )
                    validators_keys_list.append(validator_key[0])
                    index += 1
    return validators_keys_list


def get_report_interval(contract, provider):
    report_interval = contract.functions.getReportIntervalDurationSeconds().call(
        {'from': provider.eth.defaultAccount.address}
    )
    return report_interval
