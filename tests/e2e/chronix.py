import requests

from src import variables


CHRONIX_URL = 'http://0.0.0.0:8080/'


def create_fork(block_num: int):
    response = requests.post(
        CHRONIX_URL + 'v1/env/hardhat/',
        json={
            'chainId': 1,
            'fork': variables.EXECUTION_CLIENT_URI[0],
            'forking': {
                # Is valid only for mainnet fork
                'url': variables.EXECUTION_CLIENT_URI[0],
                'blockNumber': block_num,
            },
        },
        headers={'Content-Type': 'application/json'},
        timeout=10,
    )
    print(response.text)
    assert response.status_code == 200
    return response.json()['data']['port']


def delete_fork(port: int):
    response = requests.delete(CHRONIX_URL + f'v1/env/hardhat/{port}/', timeout=10)
    assert response.status_code == 200


def add_simple_dvt_module(port: int):
    response = requests.post(CHRONIX_URL + 'v1/env/' + str(port) + '/simple-dvt/deploy/', timeout=10)
    assert response.status_code == 200

    return response.json()['data']


def add_node_operator(port: int, name: str, staking_module_address: str, reward_address: str):
    response = requests.post(
        CHRONIX_URL + 'v1/env/' + str(port) + '/simple-dvt/add-node-operator/',
        json={
            'name': name,
            # 'norAddress': r1.json()['data']['stakingRouterData']['stakingModules'][1]['stakingModuleAddress'],
            'norAddress': staking_module_address,
            'rewardAddress': reward_address,
        },
        timeout=10,
    )

    assert response.status_code == 200
    return response.json()['data']


def add_node_operator_keys(
    port: int, node_operator_id: int, staking_module_address: str, keys: list[str], signatures: list[str]
):
    assert len(keys) == len(signatures)

    response = requests.post(
        CHRONIX_URL + 'v1/env/' + str(port) + '/simple-dvt/add-node-operator-keys/',
        json={
            'noId': node_operator_id,
            'norAddress': staking_module_address,
            'keysCount': len(keys),
            'keys': '0x' + ''.join([k[2:] for k in keys]),
            'signatures': '0x' + ''.join([s[2:] for s in signatures]),
        },
        timeout=10,
    )

    print(response.text)
    assert response.status_code == 200

    return response.json()['data']
