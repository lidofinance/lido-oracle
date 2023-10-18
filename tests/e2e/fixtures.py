import json
from types import MethodType
from typing import Union, cast

import pytest
from web3 import HTTPProvider

from src import variables
from src.providers.consensus.client import LiteralState
from src.providers.consensus.typings import BlockDetailsResponse, BlockRootResponse
from src.providers.keys.typings import LidoKey
from src.typings import SlotNumber, BlockRoot, BlockStamp
from src.utils.dataclass import list_of_dataclasses
from src.web3py.extensions import ConsensusClientModule, KeysAPIClientModule, LidoContracts, LidoValidatorsProvider, \
    TransactionUtils
from src.web3py.typings import Web3
from tests.e2e.chronix import create_fork, delete_fork, add_simple_dvt_module, add_node_operator, add_node_operator_keys

ADMIN = '0x3e40D73EB977Dc6a537aF587D48316feE66E9C8c'
NO_ADDRESS = '0x66d64a54E2bF860400eE2E1e8F117f687895993b'
ARAGON_VOTING = '0x2e59A20f205bB85a89C53f1936454680651E618e'
DEPOSIT_SECURITY_MODULE = '0xC77F8768774E1c9244BEed705C4354f2113CFc09'
REPORTABLE_SLOT_ACCOUNTING = 7502399
REPORTABLE_BLOCK_ACCOUNTING = 18312776

VALIDATOR_KEYS = [
    (
        '0xb07e07e4633330b730a7bbfd1d13b249d99c79df68e75f923364e9efe7f2d52b8608f9ea5551026982eecafb6d760c75',
        '0x88584e441685b4b3e4b0b278c0831c08bc2f5537bd0066c176b6dc4bd233f7adb666d52ac3e9ea3c866df1480f263e260fa0a16d56b4b2cd4b123dfc69283fb902b0177a8c8ac192954c32a6f1d6cc2ab10cb0ae38affcc3123c3c812a0692d9'
    ),  # Active validator
    (
        '0xb71a8cdd06e326d8f5176a3b908b377a26687a5eeecfa1a2d5e391026db4ebdb827bf88fe7c5ad46e368c1800e6ba330',
        '0x9694fc98bccd00659f2a2838b9f5ba2192149bfb629168162ab19d87b6ab649f4d5ea61e7d34f04abe5750c20dc3487a0682157d0fc081bdc9dede197d45eebb7802d43654767e08409b8892d9f4ec855f61900d0c7ce040d960255d8be98187',
    ),  # Pending
    (
        '0xa8a9c928432981a3229f8f5a692ab601974626b19d119dfbce53009e6600da5dde643e11ce0259f7a33e26292ff55d85',
        '0x812192d16821d765e281692a2b06f0f34dee93a0498e00a1c3fa2f27d0da4caa03373fe32d7f87ca289f0f6c5882c816073825b270929a33f90fc1bf835f51310d97df2b1f6ac400c435bc047252b9deb743e9a0d902bbb3888baea6856521bc',
    ),  # Exited
    (
        '0x900e41b90bf9dee90f31ae051492d2091032ba082d082b5db6583a8a369c8de773858cadbc6fa604da7bcd09e3e34826',
        '0xb05e6bd30f46966d70eec7d5b975f5a73600b60e188a277069fd32ca03eba659ad426b2bd66cec2ae6e2de470bc0e03d14183f6894b7653b536309eb4ed9975a5bd797c7550cf95a00d58e1e3a39fc5fa4e1930fcbde8c66d97c058e32780d54',
    ),  # Active Stuck
    (
        '0x85fd0ee4ecec6b9d674158ef62245e49924df6b6912a5e4e371bb867daeabbe56fdb35d23e64159a05c4721dc934fa22',
        '0xb624091499da830168391332c2f84ce71ca9934c6a893cb37ea57cd2ea4c7ef7d64cd88d91fd0699a1960ea633344d37193c67989f0fe92290e31b98e3a12d6d6ec692df0bbef23871205b3ecf049ddf7672549394c55ee687dd7b2fa36a921a',
    ),  # Free
]


REPORTABLE_SLOT_EJECTOR = 7514399
REPORTABLE_BLOCK_EJECTOR = 18324684


def _get_block_details(self, state_id: Union[SlotNumber, BlockRoot]) -> BlockDetailsResponse:
    data, _ = self._get(
        self.API_GET_BLOCK_DETAILS,
        path_params=(state_id,),
        force_raise=self._raise_last_missed_slot_error,
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
            force_raise=self._raise_last_missed_slot_error,
        )

        return BlockRootResponse.from_response(**data)

    return _get_block_root


@pytest.fixture
def accounting_ready_fork():
    """Returns ready for with accounting ready to report"""
    port, module_address = prepare_fork(REPORTABLE_BLOCK_ACCOUNTING)
    yield (f'http://0.0.0.0:{port}', module_address)
    delete_fork(port)


@pytest.fixture
def ejector_ready_fork():
    port, module_address = prepare_fork(REPORTABLE_BLOCK_EJECTOR)
    yield (f'http://0.0.0.0:{port}', module_address)
    delete_fork(port)


def prepare_fork(from_block):
    port = create_fork(from_block)

    module = add_simple_dvt_module(port)
    module_address = module['stakingRouterData']['stakingModules'][1]['stakingModuleAddress']

    node_operator = add_node_operator(port, 'NodeOperator', module_address, NO_ADDRESS)

    add_node_operator_keys(
        port,
        node_operator['nodeOperatorId'],
        module_address,
        [k[0] for k in VALIDATOR_KEYS],
        [k[1] for k in VALIDATOR_KEYS],
    )

    set_no_limits(
        Web3(HTTPProvider(f'http://0.0.0.0:{port}')),
        module_address,
        node_operator['nodeOperatorId'],
        5,
    )

    return (port, module_address)


@pytest.fixture
def accounting_web3(accounting_ready_fork):
    web3 = Web3(HTTPProvider(accounting_ready_fork[0], request_kwargs={'timeout': 3600}))
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)

    cc.get_block_root = MethodType(get_block_root_func(REPORTABLE_SLOT_ACCOUNTING), cc)
    cc.get_block_details = MethodType(_get_block_details, cc)

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
            'moduleAddress': accounting_ready_fork[1],
            'operatorIndex': 0,
            'depositSignature': k[1],
        } for index, k in enumerate(VALIDATOR_KEYS)])
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

    def _fetch_indexes(self, module_id, node_operators_ids_in_module):
        class A:
            def call(self, block_identifier=None):
                return [757031]

        if module_id == 2:
            return A()

        return self._getLastRequestedValidatorIndices(module_id, node_operators_ids_in_module)

    web3.lido_contracts.validators_exit_bus_oracle.functions._getLastRequestedValidatorIndices = web3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices
    web3.lido_contracts.validators_exit_bus_oracle.functions.getLastRequestedValidatorIndices = MethodType(
        _fetch_indexes,
        web3.lido_contracts.validators_exit_bus_oracle.functions,
    )

    web3.lido_contracts._load_contracts = lambda: None

    yield web3


@pytest.fixture
def ejector_web3(ejector_ready_fork):
    web3 = Web3(HTTPProvider(ejector_ready_fork[0], request_kwargs={'timeout': 3600}))
    cc = ConsensusClientModule(variables.CONSENSUS_CLIENT_URI, web3)
    kac = KeysAPIClientModule(variables.KEYS_API_URI, web3)

    cc.get_block_root = MethodType(get_block_root_func(REPORTABLE_SLOT_EJECTOR), cc)
    cc.get_block_details = MethodType(_get_block_details, cc)

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
            'moduleAddress': ejector_ready_fork[1],
            'operatorIndex': 0,
            'depositSignature': k[1],
        } for index, k in enumerate(VALIDATOR_KEYS)])
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

    do_deposits(web3, 4, 2)

    web3.lido_contracts.lido.functions.approve(web3.lido_contracts.withdrawal_queue_nft.address, 50000*10**18).transact({'from': DEPOSIT_SECURITY_MODULE})
    web3.lido_contracts.withdrawal_queue_nft.functions.requestWithdrawals([1000*10**18]*34, DEPOSIT_SECURITY_MODULE).transact({"from": DEPOSIT_SECURITY_MODULE})

    web3.lido_contracts.staking_router.functions.updateTargetValidatorsLimits(
        2,
        0,
        True,
        0
    ).transact({'from': ADMIN})

    web3.lido_contracts.staking_router.functions.updateTargetValidatorsLimits(
        1,
        1,
        False,
        0
    ).transact({'from': ADMIN})

    limits = web3.lido_contracts.oracle_report_sanity_checker.functions.getOracleReportLimits().call()

    web3.lido_contracts.oracle_report_sanity_checker.functions.grantRole(
        '0x5bf88568a012dfc9fe67407ad6775052bddc4ac89902dea1f4373ef5d9f1e35b',
        ADMIN
    ).transact({'from': ADMIN})

    web3.lido_contracts.oracle_report_sanity_checker.functions.setOracleReportLimits(
        (
            limits[0],
            limits[1],
            limits[2],
            limits[3],
            1,  # maxValidatorExitRequestsPerReport
            limits[5],
            limits[6],
            limits[7],
            limits[8],
        )
    ).transact({'from': ADMIN})

    yield web3


def add_account_to_guardians(web3, cc_address):
    cc_contract = web3.eth.contract(
        address=cc_address,
        abi=web3.lido_contracts.load_abi('HashConsensus'),
        decode_tuples=True,
    )

    guardians = cc_contract.functions.getMembers().call()

    cc_contract.functions.grantRole(
        '0x66a484cf1a3c6ef8dfd59d24824943d2853a29d96f34a01271efc55774452a51',
        ADMIN,
    ).transact({'from': ADMIN})
    for num, guardian in enumerate(guardians[0]):
        cc_contract.functions.removeMember(guardian, len(guardians[0]) - num).transact({'from': ADMIN})

    cc_contract.functions.addMember(variables.ACCOUNT.address, 1).transact({'from': ADMIN})
    web3.provider.make_request(
        'hardhat_setBalance',
        [variables.ACCOUNT.address, '0x10000000000000000000'],
    )


@pytest.fixture
def setup_accounting_account(accounting_web3):
    cc_address = accounting_web3.lido_contracts.accounting_oracle.functions.getConsensusContract().call()
    add_account_to_guardians(accounting_web3, cc_address)
    yield


@pytest.fixture
def setup_ejector_account(ejector_web3):
    cc_address = ejector_web3.lido_contracts.validators_exit_bus_oracle.functions.getConsensusContract().call()
    add_account_to_guardians(ejector_web3, cc_address)
    yield


def set_no_limits(accounting_web3, staking_module_address, node_operator_id, no_limit):
    with open('assets/NodeOperatorRegistry.json', 'r') as f:
        staking_module = accounting_web3.eth.contract(
            staking_module_address,
            abi=json.loads(f.read())
        )

    res = staking_module.functions.setNodeOperatorStakingLimit(node_operator_id, no_limit).transact({'from': ARAGON_VOTING})
    assert res


def do_deposits(web3, deposits_count: int, staking_module_id: int):
    web3.provider.make_request('hardhat_impersonateAccount', [DEPOSIT_SECURITY_MODULE])
    web3.provider.make_request('hardhat_setBalance', [DEPOSIT_SECURITY_MODULE, '0x100000000000000000000'])
    web3.lido_contracts.lido.functions.submit(web3.eth.accounts[0]).transact({
        "from": DEPOSIT_SECURITY_MODULE,
        "to": web3.lido_contracts.lido.address,
        "value": 50000 * 10 ** 18
    })
    res = web3.lido_contracts.lido.functions.deposit(deposits_count, staking_module_id, b'').transact({
        'from': DEPOSIT_SECURITY_MODULE,
    })

    assert res
