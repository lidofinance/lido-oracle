from functools import lru_cache
from types import MethodType
from typing import cast

import pytest
from web3 import HTTPProvider

from src import variables
from src.modules.accounting.accounting import Accounting
from src.providers.consensus.client import ConsensusClient
from src.providers.keys.typings import LidoKey
from src.typings import BlockStamp
from src.utils.dataclass import list_of_dataclasses
from src.web3py.extensions import ConsensusClientModule, KeysAPIClientModule, LidoContracts, LidoValidatorsProvider, \
    TransactionUtils
from src.web3py.typings import Web3
from tests.e2e import create_fork, REPORTABLE_BLOCK_ACCOUNTING, add_simple_dvt_module, NO_ADDRESS, add_node_operator, \
    add_node_operator_keys, add_account_to_guardians, VALIDATOR_KEYS, set_no_limits, REPORTABLE_SLOT_ACCOUNTING, \
    get_block_root_func, delete_fork
from tests.e2e.fixtures import _get_block_details, do_deposits, fix_fork_get_balance, ADMIN


@pytest.fixture
def create_fork_with_full_module():
    port = create_fork(REPORTABLE_BLOCK_ACCOUNTING)
    module = add_simple_dvt_module(port)

    cc = ConsensusClient(
        variables.CONSENSUS_CLIENT_URI,
        variables.HTTP_REQUEST_TIMEOUT_CONSENSUS,
        variables.HTTP_REQUEST_RETRY_COUNT_CONSENSUS,
        variables.HTTP_REQUEST_SLEEP_BEFORE_RETRY_IN_SECONDS_CONSENSUS,
    )

    blockstamp = BlockStamp('0xdb57355d2d6f340078b0288bbac1cc612ccaa57d400609f8b8cef5d5dfeb8772', None, None, None, None)
    validators = cc.get_validators_no_cache(blockstamp)

    vals = filter(lambda v: v.status == 'active_ongoing', validators)
    ex_vals = filter(lambda v: v.status == 'withdrawal_done', validators)

    lido_new_keys = []

    for module_address in (
        module['stakingRouterData']['stakingModules'][1]['stakingModuleAddress'],
        # module['stakingRouterData']['stakingModules'][0]['stakingModuleAddress'],
    ):
        for i in range(100):
            node_operator = add_node_operator(port, f'NodeOperator{i}', module_address, NO_ADDRESS)

            active_val = next(vals)
            active_val_1 = next(vals)
            exited_val = next(ex_vals)

            lido_new_keys.append((active_val.validator.pubkey, module_address, node_operator['nodeOperatorId']))
            lido_new_keys.append((active_val_1.validator.pubkey, module_address, node_operator['nodeOperatorId']))
            lido_new_keys.append((exited_val.validator.pubkey, module_address, node_operator['nodeOperatorId']))

            add_node_operator_keys(
                port,
                node_operator['nodeOperatorId'],
                module_address,
                [active_val.validator.pubkey, exited_val.validator.pubkey],
                [VALIDATOR_KEYS[0][1], VALIDATOR_KEYS[0][1]],
            )

            set_no_limits(
                Web3(HTTPProvider(f'http://0.0.0.0:{port}')),
                module_address,
                node_operator['nodeOperatorId'],
                2,
            )

    web3: Web3 = Web3(HTTPProvider(f'http://0.0.0.0:{port}', request_kwargs={'timeout': 3600}))
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)

    cc.get_block_root = MethodType(get_block_root_func(REPORTABLE_SLOT_ACCOUNTING), cc)
    cc.get_block_details = MethodType(_get_block_details, cc)

    @lru_cache(maxsize=1)
    @list_of_dataclasses(LidoKey.from_response)
    def _get_used_lido_keys(self, blockstamp: BlockStamp):
        # Because of unstable KAPI
        while True:
            try:
                response = cast(list[dict], self._get_with_blockstamp(self.USED_KEYS, blockstamp))
            except:
                pass
            else:
                break

        response.extend([{
            'key': k[0],
            'used': True,
            'moduleAddress': k[1],
            'operatorIndex': k[2],
            'depositSignature': VALIDATOR_KEYS[0][1],
        } for index, k in enumerate(lido_new_keys)])
        return response

    kac.get_used_lido_keys = MethodType(_get_used_lido_keys, kac)

    web3.attach_modules({
        'lido_contracts': LidoContracts,
        'lido_validators': LidoValidatorsProvider,
        'transaction': TransactionUtils,
        # Mocks
        'cc': lambda: cc,  # type: ignore[dict-item]
        'kac': lambda: kac,  # type: ignore[dict-item]
    })

    # def _fetch_indexes(self, module_id, node_operators_ids_in_module):
    #     class A:
    #         def call(self, block_identifier=None):
    #             return [10**10] * len(node_operators_ids_in_module)
    #
    #     if module_id == 2:
    #         return A()
    #
    #     return self._getLastRequestedValidatorIndices(module_id, node_operators_ids_in_module)
    #
    # web3.lido_contracts.validators_exit_bus_oracle.functions._getLastRequestedValidatorIndices = web3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices
    # web3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices = MethodType(
    #     _fetch_indexes,
    #     web3.lido_contracts.validators_exit_bus_oracle.functions,
    # )

    for j in range(3):
        do_deposits(web3, 100, 2)
        print(f'deposit done {j}')

    yield web3

    delete_fork(port)


@pytest.mark.e2e
def test_gas_estimation(create_fork_with_full_module, remove_sleep, caplog):
    variables.ALLOW_REPORTING_IN_BUNKER_MODE = True
    web3 = create_fork_with_full_module

    fix_fork_get_balance(web3)

    cc_address = web3.lido_contracts.accounting_oracle.functions.getConsensusContract().call()
    add_account_to_guardians(web3, cc_address)

    a = Accounting(web3)
    a.run_cycle(a._get_latest_blockstamp())

    assert True

