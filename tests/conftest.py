from pathlib import Path

import pytest
from _pytest.fixtures import FixtureRequest
from web3.providers import JSONBaseProvider
from web3.middleware import simple_cache_middleware
from web3.types import Timestamp

from src.variables import CONSENSUS_CLIENT_URI, EXECUTION_CLIENT_URI, KEYS_API_URI
from src.typings import BlockStamp, SlotNumber, BlockNumber, EpochNumber, ReferenceBlockStamp
from src.web3py.extentions import LidoContracts, TransactionUtils, LidoValidatorsProvider
from src.web3py.typings import Web3

from src.web3py.contract_tweak import tweak_w3_contracts
from tests.providers import (
    ResponseToFileProvider,
    ResponseFromFile,
    MockProvider,
    ResponseToFileConsensusClientModule,
    ResponseFromFileConsensusClientModule,
    ResponseToFileKeysAPIClientModule,
    ResponseFromFileKeysAPIClientModule,
    UpdateResponsesProvider,
    UpdateResponsesConsensusClientModule,
    UpdateResponsesKeysAPIClientModule,
)


def pytest_addoption(parser):
    parser.addoption(
        "--save-responses",
        action="store_true",
        default=False,
        help="Save responses from web3 providers",
    )
    parser.addoption(
        "--update-responses",
        action="store_true",
        default=False,
        help="Update responses from web3 providers. "
             "New responses will be added to the files, unused responses will be removed.",
    )


@pytest.fixture()
def responses_path(request: FixtureRequest) -> Path:
    return Path('fixtures') / request.node.parent.name / (request.node.name + '.json')


# ----- Web3 Provider Mock -----
@pytest.fixture()
def response_to_file_provider(responses_path) -> ResponseToFileProvider:
    provider = ResponseToFileProvider(EXECUTION_CLIENT_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def update_responses_provider(responses_path) -> UpdateResponsesProvider:
    provider = UpdateResponsesProvider(responses_path, EXECUTION_CLIENT_URI)
    yield provider
    provider.save_responses(responses_path)


@pytest.fixture()
def mock_provider(responses_path) -> MockProvider:
    provider = MockProvider(fallback_provider=ResponseFromFile(responses_path))
    return provider


@pytest.fixture()
def provider(request, responses_path) -> JSONBaseProvider:
    if request.config.getoption("--save-responses"):
        return request.getfixturevalue("response_to_file_provider")

    if request.config.getoption("--update-responses"):
        return request.getfixturevalue("update_responses_provider")

    return request.getfixturevalue("mock_provider")


@pytest.fixture()
def web3(provider) -> Web3:
    web3 = Web3(provider)
    tweak_w3_contracts(web3)
    web3.middleware_onion.add(simple_cache_middleware)

    yield web3


# ---- Consensus Client Mock ----
@pytest.fixture()
def response_to_file_cl_client(web3, responses_path) -> ResponseToFileConsensusClientModule:
    client = ResponseToFileConsensusClientModule(CONSENSUS_CLIENT_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.cl.json'))


@pytest.fixture()
def update_responses_cl_client(web3, responses_path) -> UpdateResponsesConsensusClientModule:
    client = UpdateResponsesConsensusClientModule(responses_path, CONSENSUS_CLIENT_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.cl.json'))


@pytest.fixture()
def consensus_client(request, responses_path, web3):
    if request.config.getoption("--save-responses"):
        client = request.getfixturevalue("response_to_file_cl_client")
    elif request.config.getoption("--update-responses"):
        client = request.getfixturevalue("update_responses_cl_client")
    else:
        client = ResponseFromFileConsensusClientModule(responses_path.with_suffix('.cl.json'), web3)
    web3.attach_modules({"cc": lambda: client})


# ---- Keys API Client Mock ----
@pytest.fixture()
def response_to_file_ka_client(web3, responses_path) -> ResponseToFileKeysAPIClientModule:
    client = ResponseToFileKeysAPIClientModule(KEYS_API_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.ka.json'))


@pytest.fixture()
def update_responses_ka_client(web3, responses_path) -> UpdateResponsesKeysAPIClientModule:
    client = UpdateResponsesKeysAPIClientModule(responses_path, KEYS_API_URI, web3)
    yield client
    client.save_responses(responses_path.with_suffix('.ka.json'))


@pytest.fixture()
def keys_api_client(request, responses_path, web3):
    if request.config.getoption("--save-responses"):
        client = request.getfixturevalue("response_to_file_ka_client")
    elif request.config.getoption("--update-responses"):
        client = request.getfixturevalue("update_responses_ka_client")
    else:
        client = ResponseFromFileKeysAPIClientModule(responses_path.with_suffix('.ka.json'), web3)
    web3.attach_modules({"kac": lambda: client})


# ---- Lido contracts ----
class Contracts(LidoContracts):
    """Hardcoded addresses to simplify building fixtures"""
    def _load_contracts(self):
        self.lido_locator = self.w3.eth.contract(
            address='0x12cd349E19Ab2ADBE478Fc538A66C059Cf40CFeC',
            abi=self.load_abi('LidoLocator'),
        )

        self.lido = self.w3.eth.contract(
            address='0xEC9ac956D7C7fE5a94919fD23BAc4a42f950A403',
            abi=self.load_abi('Lido'),
            decode_tuples=True,
        )

        self.accounting_oracle = self.w3.eth.contract(
            address='0x5704fb15ba3E56383a93A33ca2Fc5Ec4C8B7Cb3a',
            abi=self.load_abi('AccountingOracle'),
            decode_tuples=True,
        )

        self.staking_router = self.w3.eth.contract(
            address='0xDd7d15490748a803AeC6987046311AF76a5A6502',
            abi=self.load_abi('StakingRouter'),
            decode_tuples=True,
        )

        self.validators_exit_bus_oracle = self.w3.eth.contract(
            address='0x5c7Ba617C0B25835554Fa93D031294aA0878DAb2',
            abi=self.load_abi('ValidatorsExitBusOracle'),
            decode_tuples=True,
        )

        self.withdrawal_queue_nft = self.w3.eth.contract(
            address='0x7D22F2B8319e51055C88778BcD6658c2982c696b',
            abi=self.load_abi('WithdrawalRequestNFT'),
            decode_tuples=True,
        )
        self.oracle_report_sanity_checker = self.w3.eth.contract(
            address='0xC9F35dfd24588A2db1398d60B3391CC14CA00C3B',
            abi=self.load_abi('OracleReportSanityChecker'),
            decode_tuples=True
        )
        self.oracle_daemon_config = self.w3.eth.contract(
            address='0xce59E362b6a91bC090775B230e4EFe791d5005FB',
            abi=self.load_abi('OracleDaemonConfig'),
            decode_tuples=True,
        )

        self.oracle_daemon_config = self.w3.eth.contract(
            address='0xce59E362b6a91bC090775B230e4EFe791d5005FB',
            abi=self.load_abi('OracleDaemonConfig'),
            decode_tuples=True,
        )


@pytest.fixture()
def contracts(web3):
    web3.attach_modules({
        'lido_contracts': Contracts,
    })


# ---- Transaction Utils
@pytest.fixture()
def tx_utils(web3):
    web3.attach_modules({
        'transaction': TransactionUtils,
    })


# ---- Lido validators ----
@pytest.fixture()
def lido_validators(web3, consensus_client, keys_api_client):
    web3.attach_modules({
        'lido_validators': LidoValidatorsProvider,
    })


def get_blockstamp_by_state(w3, state_id) -> BlockStamp:
    root = w3.cc.get_block_root(state_id).root
    slot_details = w3.cc.get_block_details(root)

    return ReferenceBlockStamp(
        block_root=root,
        slot_number=SlotNumber(int(slot_details.message.slot)),
        state_root=slot_details.message.state_root,
        block_number=BlockNumber(int(slot_details.message.body['execution_payload']['block_number'])),
        block_hash=slot_details.message.body['execution_payload']['block_hash'],
        block_timestamp=Timestamp(slot_details.message.body['execution_payload']['timestamp']),
        ref_slot=SlotNumber(int(slot_details.message.slot)),
        ref_epoch=EpochNumber(int(int(slot_details.message.slot)/12)),
    )
