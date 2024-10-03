import logging
import os
from types import MethodType
from typing import Union

import pytest
import requests

from pytest import Item

from web3 import Web3, HTTPProvider

from src import variables
from src.providers.consensus.client import LiteralState
from src.providers.consensus.types import BlockDetailsResponse, BlockRootResponse
from src.types import SlotNumber, BlockRoot
from src.web3py.extensions import (
    LidoContracts,
    LidoValidatorsProvider,
    TransactionUtils,
    ConsensusClientModule,
    KeysAPIClientModule,
)
from tests.e2e.fork import anvil_fork

# Mainnet admin
ADMIN = '0x3e40D73EB977Dc6a537aF587D48316feE66E9C8c'


@pytest.hookimpl(hookwrapper=True)
def pytest_collection_modifyitems(items: list[Item]):
    yield
    if any(not item.get_closest_marker("e2e") for item in items):
        for item in items:
            if item.get_closest_marker("e2e"):
                item.add_marker(
                    pytest.mark.skip(
                        reason="e2e tests are take a lot of time and skipped if any other tests are selected"
                    )
                )


def _get_block_details(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockDetailsResponse:
    data, _ = self._get(
        self.API_GET_BLOCK_DETAILS,
        path_params=(state_id,),
    )
    bs_e = self.w3.eth.get_block('latest')
    data['message']['body']['execution_payload']['block_number'] = str(bs_e.number)
    data['message']['body']['execution_payload']['block_hash'] = bs_e.hash.hex()
    data['message']['body']['execution_payload']['timestamp'] = str(bs_e.timestamp)
    return BlockDetailsResponse.from_response(**data)


def get_block_root_func(reportable_slot):
    def _get_block_root(self, state_id: Union[SlotNumber, BlockRoot, LiteralState]):
        # To avoid Deadline missed error
        if state_id in ['finalized', 'head']:
            state_id = reportable_slot

        data, _ = self._get(
            self.API_GET_BLOCK_ROOT,
            path_params=(state_id,),
        )

        return BlockRootResponse.from_response(**data)

    return _get_block_root


@pytest.fixture(scope="function")
def web3_anvil(request):
    """
    param request - Tuple[slot_num, block_num]
    """
    with anvil_fork(
        os.getenv('ANVIL_PATH', ''),
        variables.EXECUTION_CLIENT_URI[0],
        request.param[1],
    ):
        w3 = Web3(HTTPProvider('http://127.0.0.1:8545'))
        cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, w3)
        cc.get_block_root = MethodType(get_block_root_func(request.param[0]), cc)
        cc.get_block_details = MethodType(_get_block_details, cc)
        kac = KeysAPIClientModule(variables.KEYS_API_URI, w3)

        w3.attach_modules(
            {
                'lido_contracts': LidoContracts,
                'lido_validators': LidoValidatorsProvider,
                'transaction': TransactionUtils,
                'cc': lambda: cc,  # type: ignore[dict-item]
                'kac': lambda: kac,  # type: ignore[dict-item]
            }
        )
        #w3.provider.make_request('evm_setAutomine', [1])
        yield w3



SYNC_CONFIGS = {
    'repo': 'lidofinance/lido-dao',
    'branch': 'master',
    'contracts': [
        {
            'name': 'Accounting Oracle',
            'remote_bin': 'contracts/0.8.9/oracle/AccountingOracle.sol',
            'remote_abi': 'contracts/0.8.9/oracle/AccountingOracle.sol',
            'eth_address': {
                1: '0xFdDf38947aFB03C621C71b06C9C70bce73f12999',
            },
        },
    ],
}


def get_file_from_github(repo, branch, file_path):
    url = f'https://raw.githubusercontent.com/{repo}/{branch}/{file_path}'
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as error:
        logging.error({'msg': 'Contract download exception.', 'error': str(error)})
        raise error


def increase_balance(web3, address, balance):
    web3.provider.make_request('anvil_setBalance', [address, balance])


def upgrade_contract(web3, proxy_address, contract_bytecode, contract_abi):
    # Create a contract object
    contract = web3.eth.contract(abi=contract_abi, bytecode=contract_bytecode)

    # Deploy the contract
    tx_hash = contract.constructor().transact()
    tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    contract_address = tx_receipt.contractAddress

    proxy = web3.eth.contract(
        address=proxy_address,
        # Proxy abi
        abi=web3.lido_contracts.load_abi('OracleDaemonConfig'),
    )

    admin = proxy.functions.proxy__getAdmin().call()

    increase_balance(web3, admin, 10 ** 18)

    proxy.functions.proxy__upgradeTo(contract_address).transact({"from": admin})

    web3.eth.contract(abi=contract_abi, address=proxy_address)


@pytest.fixture
def upgrade_contracts(web3_anvil):
    chain_id = web3_anvil.eth.chain_id
    for contract in SYNC_CONFIGS['contracts']:
        if chain_id in contract['eth_address']:
            contract_source = get_file_from_github(SYNC_CONFIGS['repo'], SYNC_CONFIGS['branch'], contract['remote_bin'])
            contract_abi = get_file_from_github(SYNC_CONFIGS['repo'], SYNC_CONFIGS['branch'], contract['remote_abi'])

            upgrade_contract(web3_anvil, contract['eth_address'][chain_id], contract_source, contract_abi)

            # Example with contract compilation
            # -----------------------
            # result = compile_source("""// SPDX-FileCopyrightText: 2023 Lido <info@lido.fi>
            # // SPDX-License-Identifier: GPL-3.0
            # pragma solidity 0.8.9;
            # contract MyContract {
            #     uint256 public myData; // Public state variable
            #
            #     // Function to set data
            #     function setData(uint256 _newValue) public {
            #         myData = _newValue;
            #     }
            #
            #     // Public function to read data
            #     function getData() public view returns (uint256) {
            #         return myData;
            #     }
            # }
            # """, solc_version='0.8.9')
            # upgrade_contract(web3_accounting, contract['eth_address'][chain_id], result['<stdin>:MyContract']['bin'], result['<stdin>:MyContract']['abi'])


def set_only_guardian(w3, consensus, address, admin):
    oracles = consensus.functions.getMembers().call()
    quorum_size = consensus.functions.getQuorum().call()

    consensus.functions.grantRole(
        '0x66a484cf1a3c6ef8dfd59d24824943d2853a29d96f34a01271efc55774452a51',
        admin,
    ).transact({'from': admin})

    for index, guardian in enumerate(oracles.addresses):
        h = consensus.functions.removeMember(guardian, quorum_size).transact({"from": admin})
        #w3.eth.wait_for_transaction_receipt(h)

    consensus.functions.addMember(address, 1).transact({"from": admin})
